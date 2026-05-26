from __future__ import annotations

import base64
import json
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field
from pypdf import PdfReader

from enzyme_recommender.ingestion.mineru import sha256_file


DocumentStatus = Literal[
    "uploaded",
    "deduplicated",
    "mineru_submitted",
    "mineru_succeeded",
    "rag_built",
    "evidence_extracted",
    "indexed",
    "retrieval_verified",
    "searchable",
    "failed_upload_validation",
    "failed_mineru",
    "failed_rag_build",
    "failed_evidence",
    "failed_indexing",
    "failed_retrieval_verification",
    "needs_review",
]

JobStage = Literal[
    "upload_validation",
    "mineru_parse",
    "rag_build",
    "evidence_extract",
    "qdrant_index",
    "retrieval_verify",
    "complete",
]

JobStatus = Literal["queued", "running", "succeeded", "failed", "skipped"]


class IngestionBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class IngestionDocument(IngestionBaseModel):
    document_id: str
    source_pdf: str
    original_filename: str
    sha256: str
    size_bytes: int
    page_count: int
    raw_pdf_path: str
    upload_batch_id: Optional[str] = None
    uploaded_at: str
    uploaded_by: str = "api"
    current_status: DocumentStatus = "uploaded"
    active_task_id: Optional[str] = None
    active_artifact_dir: Optional[str] = None
    active_artifact_version: Optional[str] = None
    active_rag_dir: Optional[str] = None
    active_evidence_dir: Optional[str] = None
    active_collection: Optional[str] = None
    active_index_version: Optional[str] = None
    last_error_code: Optional[str] = None
    last_error_message: Optional[str] = None
    updated_at: str


class IngestionJob(IngestionBaseModel):
    job_id: str
    document_id: str
    sha256: str
    upload_batch_id: Optional[str] = None
    stage: JobStage = "upload_validation"
    status: JobStatus = "queued"
    attempt: int = 1
    created_at: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    updated_at: str
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class IngestionBatch(IngestionBaseModel):
    batch_id: str
    created_at: str
    uploaded_by: str = "api"
    document_ids: List[str]
    sha256_values: List[str]


class RegisteredDocument(IngestionBaseModel):
    document: IngestionDocument
    duplicate: bool = False


class IngestionFilePayload(IngestionBaseModel):
    filename: str
    content_base64: str

    def decode(self) -> bytes:
        return base64.b64decode(self.content_base64, validate=True)


class IngestionRegistry:
    def __init__(self, artifact_root: Path) -> None:
        self.artifact_root = artifact_root.expanduser().resolve()
        self.upload_root = self.artifact_root / "uploads"
        self.raw_upload_dir = self.upload_root / "raw"
        self.staging_dir = self.upload_root / "staging"
        self.batch_dir = self.upload_root / "batches"
        self.registry_dir = self.artifact_root / "ingestion_registry"
        self.documents_path = self.registry_dir / "documents.jsonl"
        self.jobs_path = self.registry_dir / "jobs.jsonl"

    def ensure_dirs(self) -> None:
        for path in [self.raw_upload_dir, self.staging_dir, self.batch_dir, self.registry_dir]:
            path.mkdir(parents=True, exist_ok=True)

    def register_pdf_path(
        self,
        pdf_path: Path,
        batch_id: Optional[str] = None,
        uploaded_by: str = "api",
        original_filename: Optional[str] = None,
    ) -> RegisteredDocument:
        self.ensure_dirs()
        source_path = pdf_path.expanduser().resolve()
        validate_pdf_path(source_path)
        page_count = count_pdf_pages_or_raise(source_path)
        digest = sha256_file(source_path)
        existing = self.find_document_by_sha256(digest)
        if existing:
            if batch_id and existing.upload_batch_id != batch_id:
                existing = existing.model_copy(
                    update={
                        "upload_batch_id": batch_id,
                        "current_status": existing.current_status,
                        "updated_at": utc_now(),
                    }
                )
                self.append_document(existing)
            return RegisteredDocument(document=existing, duplicate=True)

        filename = normalize_pdf_filename(original_filename or source_path.name)
        document_id = self.allocate_document_id(filename, digest)
        raw_path = self.raw_upload_dir / f"{digest}.pdf"
        if source_path != raw_path:
            shutil.copy2(source_path, raw_path)
        document = IngestionDocument(
            document_id=document_id,
            source_pdf=filename,
            original_filename=filename,
            sha256=digest,
            size_bytes=raw_path.stat().st_size,
            page_count=page_count,
            raw_pdf_path=str(raw_path),
            upload_batch_id=batch_id,
            uploaded_at=utc_now(),
            uploaded_by=uploaded_by,
            current_status="uploaded",
            updated_at=utc_now(),
        )
        self.append_document(document)
        document = document.model_copy(update={"current_status": "deduplicated", "updated_at": utc_now()})
        self.append_document(document)
        return RegisteredDocument(document=document, duplicate=False)

    def register_pdf_bytes(
        self,
        filename: str,
        content: bytes,
        batch_id: Optional[str] = None,
        uploaded_by: str = "api",
    ) -> RegisteredDocument:
        self.ensure_dirs()
        normalized_filename = normalize_pdf_filename(filename)
        staging_path = self.staging_dir / f"{uuid.uuid4().hex}_{normalized_filename}"
        staging_path.write_bytes(content)
        try:
            return self.register_pdf_path(
                staging_path,
                batch_id=batch_id,
                uploaded_by=uploaded_by,
                original_filename=normalized_filename,
            )
        finally:
            try:
                staging_path.unlink()
            except FileNotFoundError:
                pass

    def create_batch(
        self,
        registered_documents: Iterable[RegisteredDocument],
        uploaded_by: str = "api",
    ) -> IngestionBatch:
        self.ensure_dirs()
        documents = [item.document for item in registered_documents]
        batch_id = make_batch_id(document.sha256 for document in documents)
        batch = IngestionBatch(
            batch_id=batch_id,
            created_at=utc_now(),
            uploaded_by=uploaded_by,
            document_ids=[document.document_id for document in documents],
            sha256_values=[document.sha256 for document in documents],
        )
        self.write_batch(batch)
        for document in documents:
            if document.upload_batch_id == batch_id:
                continue
            updated = document.model_copy(update={"upload_batch_id": batch_id, "updated_at": utc_now()})
            self.append_document(updated)
        return batch

    def write_batch(self, batch: IngestionBatch) -> None:
        self.ensure_dirs()
        path = self.batch_dir / f"{batch.batch_id}.json"
        path.write_text(batch.model_dump_json(indent=2) + "\n", encoding="utf-8")

    def load_batch(self, batch_id: str) -> Optional[IngestionBatch]:
        path = self.batch_dir / f"{Path(batch_id).name}.json"
        if not path.is_file():
            return None
        return IngestionBatch.model_validate_json(path.read_text(encoding="utf-8"))

    def create_job(self, document: IngestionDocument, metadata: Optional[Dict[str, Any]] = None) -> IngestionJob:
        latest = self.latest_job_for_document(document.document_id)
        attempt = (latest.attempt + 1) if latest else 1
        job = IngestionJob(
            job_id=f"ingest_{safe_identifier(document.document_id, max_length=48)}_{uuid.uuid4().hex[:10]}",
            document_id=document.document_id,
            sha256=document.sha256,
            upload_batch_id=document.upload_batch_id,
            stage="upload_validation",
            status="queued",
            attempt=attempt,
            created_at=utc_now(),
            updated_at=utc_now(),
            metadata=metadata or {},
        )
        self.append_job(job)
        return job

    def update_job(
        self,
        job: IngestionJob,
        stage: Optional[JobStage] = None,
        status: Optional[JobStatus] = None,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> IngestionJob:
        base = self.load_jobs().get(job.job_id) or job
        update: Dict[str, Any] = {"updated_at": utc_now()}
        if stage is not None:
            update["stage"] = stage
        if status is not None:
            update["status"] = status
            if status == "running" and base.started_at is None:
                update["started_at"] = utc_now()
            if status in {"succeeded", "failed", "skipped"}:
                update["finished_at"] = utc_now()
        if error_code is not None:
            update["error_code"] = error_code
        if error_message is not None:
            update["error_message"] = error_message[:2000]
        if metadata is not None:
            merged = dict(base.metadata)
            merged.update(metadata)
            update["metadata"] = merged
        updated = base.model_copy(update=update)
        self.append_job(updated)
        return updated

    def update_document(
        self,
        document: IngestionDocument,
        status: Optional[DocumentStatus] = None,
        **fields: Any,
    ) -> IngestionDocument:
        base = self.get_document(document.document_id) or document
        update = dict(fields)
        if status is not None:
            update["current_status"] = status
        update["updated_at"] = utc_now()
        if "last_error_message" in update and update["last_error_message"]:
            update["last_error_message"] = str(update["last_error_message"])[:2000]
        updated = base.model_copy(update=update)
        self.append_document(updated)
        return updated

    def append_document(self, document: IngestionDocument) -> None:
        self.ensure_dirs()
        append_jsonl(self.documents_path, document.model_dump(mode="json"))

    def append_job(self, job: IngestionJob) -> None:
        self.ensure_dirs()
        append_jsonl(self.jobs_path, job.model_dump(mode="json"))

    def load_documents(self) -> Dict[str, IngestionDocument]:
        records: Dict[str, IngestionDocument] = {}
        for row in read_jsonl(self.documents_path):
            document = IngestionDocument.model_validate(row)
            records[document.document_id] = document
        return records

    def load_jobs(self) -> Dict[str, IngestionJob]:
        records: Dict[str, IngestionJob] = {}
        for row in read_jsonl(self.jobs_path):
            job = IngestionJob.model_validate(row)
            records[job.job_id] = job
        return records

    def list_jobs_for_document(self, document_id: str) -> List[IngestionJob]:
        return [job for job in self.load_jobs().values() if job.document_id == document_id]

    def latest_job_for_document(self, document_id: str) -> Optional[IngestionJob]:
        jobs = self.list_jobs_for_document(document_id)
        if not jobs:
            return None
        return sorted(jobs, key=lambda item: item.created_at)[-1]

    def get_document(self, document_id: str) -> Optional[IngestionDocument]:
        return self.load_documents().get(document_id)

    def find_document_by_sha256(self, sha256: str) -> Optional[IngestionDocument]:
        for document in self.load_documents().values():
            if document.sha256 == sha256:
                return document
        return None

    def allocate_document_id(self, filename: str, sha256: str) -> str:
        base = safe_identifier(Path(filename).stem, max_length=72) or f"doc_{sha256[:8]}"
        documents = self.load_documents()
        existing = documents.get(base)
        if existing is None:
            return base
        if existing.sha256 == sha256:
            return base
        candidate = f"{base}_{sha256[:8]}"
        counter = 2
        while candidate in documents and documents[candidate].sha256 != sha256:
            candidate = f"{base}_{sha256[:8]}_{counter}"
            counter += 1
        return candidate


def append_jsonl(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False)
        handle.write("\n")


def read_jsonl(path: Path) -> Iterable[Dict[str, Any]]:
    if not path.is_file():
        return []

    def _iter() -> Iterable[Dict[str, Any]]:
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                payload = json.loads(line)
                if not isinstance(payload, dict):
                    raise ValueError(f"expected JSON object at {path}:{line_number}")
                yield payload

    return _iter()


def validate_pdf_path(path: Path) -> None:
    if not path.is_file():
        raise FileNotFoundError(path)
    if path.suffix.lower() != ".pdf":
        raise ValueError(f"expected a PDF file: {path}")
    with path.open("rb") as handle:
        header = handle.read(5)
    if not header.startswith(b"%PDF"):
        raise ValueError(f"file does not look like a PDF: {path}")


def count_pdf_pages_or_raise(path: Path) -> int:
    try:
        return len(PdfReader(str(path)).pages)
    except Exception as exc:
        raise ValueError(f"cannot read PDF page count: {path}") from exc


def normalize_pdf_filename(filename: str) -> str:
    name = Path(filename).name.strip()
    if not name:
        raise ValueError("filename is required")
    if not name.lower().endswith(".pdf"):
        name = f"{name}.pdf"
    return name


def make_batch_id(sha256_values: Iterable[str] = ()) -> str:
    fingerprint = "_".join(value[:8] for value in list(sha256_values)[:8]) or uuid.uuid4().hex[:8]
    return f"batch_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{fingerprint[:16]}"


def safe_identifier(value: str, max_length: int = 80) -> str:
    normalized = re.sub(r"\s+", "_", value.strip())
    normalized = re.sub(r"[^\w.\-\u4e00-\u9fff]+", "_", normalized, flags=re.UNICODE)
    normalized = re.sub(r"_+", "_", normalized)
    normalized = normalized.strip("._-")
    if len(normalized) > max_length:
        normalized = normalized[:max_length].rstrip("._-")
    return normalized


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
