from __future__ import annotations

import json
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from enzyme_recommender.evidence import extract_evidence_records
from enzyme_recommender.ingestion.mineru import MinerUOptions
from enzyme_recommender.ingestion.registry import (
    IngestionDocument,
    IngestionJob,
    IngestionRegistry,
    safe_identifier,
)
from enzyme_recommender.rag import build_rag_inputs
from enzyme_recommender.rag.artifacts import find_mineru_auto_dir, write_json, write_jsonl
from enzyme_recommender.rag.embedding import (
    HashEmbeddingModel,
    SentenceEmbeddingModel,
)
from enzyme_recommender.rag.indexing import (
    POINT_SCHEMA_VERSION,
    build_index_identity,
    build_index_version as build_model_index_version,
)
from enzyme_recommender.rag.qdrant import QdrantRestClient, build_index_points, point_type_counts
from enzyme_recommender.runtime import RuntimeServices


RAG_BUILDER_VERSION = "rag_builder_v1"
EVIDENCE_EXTRACTOR_VERSION = "rule_extractor_v1"
DEFAULT_INDEX_VERSION_PREFIX = "ingestion_v1"


@dataclass(frozen=True)
class IngestionPipelineOptions:
    artifact_root: Path = Path("artifacts")
    poll_timeout_seconds: float = 1800.0
    poll_interval_seconds: float = 10.0
    qdrant_batch_size: int = 64
    verify_min_points: int = 1
    skip_mineru: bool = False
    reindex_only: bool = False
    delete_existing_points: bool = False
    dry_run: bool = False


@dataclass(frozen=True)
class IngestionRunResult:
    document: IngestionDocument
    job: IngestionJob
    point_counts: Dict[str, int]
    retrieval_verified: bool


class IngestionPipeline:
    def __init__(
        self,
        runtime: RuntimeServices,
        registry: IngestionRegistry,
        options: Optional[IngestionPipelineOptions] = None,
    ) -> None:
        self.runtime = runtime
        self.registry = registry
        self.options = options or IngestionPipelineOptions(artifact_root=registry.artifact_root)

    def run_document(
        self,
        document_id: str,
        job: Optional[IngestionJob] = None,
        reindex_only: Optional[bool] = None,
    ) -> IngestionRunResult:
        document = self.registry.get_document(document_id)
        if document is None:
            raise ValueError(f"unknown ingestion document: {document_id}")
        job = job or self.registry.create_job(document)
        effective_reindex_only = self.options.reindex_only if reindex_only is None else reindex_only

        job = self.registry.update_job(job, stage="mineru_parse", status="running")
        try:
            if effective_reindex_only:
                artifact_dir = require_existing_path(document.active_artifact_dir, "active_artifact_dir")
            elif self.options.skip_mineru and (cached_artifact_dir := resolve_existing_artifact_dir(document)):
                artifact_dir = cached_artifact_dir
            else:
                document, artifact_dir = self.run_mineru(document, job)

            document, rag_dir = self.build_rag(document, artifact_dir, job)
            document, evidence_dir = self.extract_evidence(document, rag_dir, job)
            document, point_counts = self.index_document(document, rag_dir, evidence_dir, job)
            document = self.verify_retrieval(document, point_counts, job)
            job = self.registry.update_job(
                job,
                stage="complete",
                status="succeeded",
                metadata={"point_counts": point_counts, "document_status": document.current_status},
            )
            return IngestionRunResult(
                document=document,
                job=job,
                point_counts=point_counts,
                retrieval_verified=document.current_status == "searchable",
            )
        except Exception as exc:
            latest_job = self.registry.load_jobs().get(job.job_id, job)
            status, stage = classify_failure(latest_job.stage)
            document = self.registry.update_document(
                document,
                status=status,
                last_error_code=stage,
                last_error_message=str(exc),
            )
            job = self.registry.update_job(latest_job, status="failed", error_code=stage, error_message=str(exc))
            raise

    def run_mineru(self, document: IngestionDocument, job: IngestionJob) -> tuple[IngestionDocument, Path]:
        client = self.runtime.document_parser()
        options = MinerUOptions(return_model_output="false", return_middle_json="true", response_format_zip="true")
        pdf_path = resolve_document_pdf_path(document.raw_pdf_path)
        task_id, payload = client.submit_pdfs([pdf_path], options=options)
        artifact_dir = self.mineru_artifact_root(document, task_id)
        manifest = client.build_manifest(task_id, [pdf_path], options=options, raw_submit_response=payload)
        manifest.artifact_dir = str(artifact_dir)
        client.write_manifest(manifest, artifact_dir)
        document = self.registry.update_document(
            document,
            status="mineru_submitted",
            active_task_id=task_id,
            active_artifact_dir=str(artifact_dir),
            active_artifact_version=parser_version(self.runtime),
            last_error_code=None,
            last_error_message=None,
        )
        self.registry.update_job(job, stage="mineru_parse", status="running", metadata={"task_id": task_id})
        if self.options.dry_run:
            return document, artifact_dir

        result = client.poll_until_done(
            task_id,
            artifact_dir=artifact_dir,
            timeout_seconds=self.options.poll_timeout_seconds,
            interval_seconds=self.options.poll_interval_seconds,
        )
        if result.artifact_path:
            extract_zip_safe(Path(result.artifact_path), artifact_dir / "extracted")
            artifact_source_dir = artifact_dir / "extracted"
        else:
            artifact_source_dir = artifact_dir
        auto_dir = find_mineru_auto_dir(artifact_source_dir)
        document = self.registry.update_document(
            document,
            status="mineru_succeeded",
            active_task_id=task_id,
            active_artifact_dir=str(auto_dir),
            active_artifact_version=parser_version(self.runtime),
        )
        return document, auto_dir

    def build_rag(
        self,
        document: IngestionDocument,
        artifact_dir: Path,
        job: IngestionJob,
    ) -> tuple[IngestionDocument, Path]:
        self.registry.update_job(job, stage="rag_build", status="running")
        rag_dir = self.options.artifact_root / "rag_inputs" / document.document_id
        outputs = build_rag_inputs(
            artifact_dir=artifact_dir,
            source_pdf=document.source_pdf,
            document_id=document.document_id,
            artifact_root=self.options.artifact_root,
        )
        if not self.options.dry_run:
            rag_dir.mkdir(parents=True, exist_ok=True)
            write_json(rag_dir / "document_manifest.json", outputs["manifest"])
            write_jsonl(rag_dir / "rag_chunks.jsonl", outputs["rag_chunks"])
            write_jsonl(rag_dir / "table_records.jsonl", outputs["table_records"])
            write_jsonl(rag_dir / "extraction_candidates.jsonl", outputs["extraction_candidates"])
        document = self.registry.update_document(
            document,
            status="rag_built",
            active_rag_dir=str(rag_dir),
            last_error_code=None,
            last_error_message=None,
        )
        self.registry.update_job(
            job,
            stage="rag_build",
            status="running",
            metadata={"rag_counts": outputs["manifest"].get("counts", {})},
        )
        return document, rag_dir

    def extract_evidence(
        self,
        document: IngestionDocument,
        rag_dir: Path,
        job: IngestionJob,
    ) -> tuple[IngestionDocument, Path]:
        self.registry.update_job(job, stage="evidence_extract", status="running")
        evidence_dir = self.options.artifact_root / "evidence" / document.document_id
        outputs = extract_evidence_records(rag_dir)
        if not self.options.dry_run:
            evidence_dir.mkdir(parents=True, exist_ok=True)
            write_jsonl(evidence_dir / "evidence_records.jsonl", outputs["evidence_records"])
            write_jsonl(evidence_dir / "review_queue.jsonl", outputs["review_queue"])
            write_json(evidence_dir / "validation_report.json", outputs["validation_report"])
        report = outputs["validation_report"]
        document = self.registry.update_document(
            document,
            status="evidence_extracted",
            active_evidence_dir=str(evidence_dir),
            last_error_code=None,
            last_error_message=None,
        )
        self.registry.update_job(
            job,
            stage="evidence_extract",
            status="running",
            metadata={"evidence_counts": report.get("output_counts", {})},
        )
        return document, evidence_dir

    def index_document(
        self,
        document: IngestionDocument,
        rag_dir: Path,
        evidence_dir: Path,
        job: IngestionJob,
    ) -> tuple[IngestionDocument, Dict[str, int]]:
        self.registry.update_job(job, stage="qdrant_index", status="running")
        embedding_model = build_embedding_model(self.runtime)
        index_identity = build_index_identity(
            embedding_model=embedding_model,
            collection=self.runtime.config.vector_store.collection,
        )
        extra_payload = {
            "point_schema_version": index_identity.point_schema_version,
            "ingestion_document_status": document.current_status,
            "ingestion_sha256": document.sha256,
            "ingestion_batch_id": document.upload_batch_id,
            "parser_provider": self.runtime.config.document_parser.provider,
            "parser_version": parser_version(self.runtime),
            "rag_builder_version": RAG_BUILDER_VERSION,
            "evidence_extractor_version": EVIDENCE_EXTRACTOR_VERSION,
            "embedding_provider": self.runtime.config.embedding.provider,
            "embedding_model": embedding_model.name,
            "embedding_dimensions": embedding_model.dimensions,
            "embedding_slug": index_identity.embedding_slug,
            "index_version": index_identity.index_version,
        }
        points = build_index_points(
            rag_input_dir=rag_dir,
            evidence_dir=evidence_dir,
            embedding_model=embedding_model,
            extra_payload=extra_payload,
            index_version=index_identity.index_version,
        )
        counts = point_type_counts(points)
        if not self.options.dry_run:
            with QdrantRestClient(self.runtime.qdrant_config()) as client:
                client.ensure_collection(vector_size=embedding_model.dimensions, recreate=False)
                if self.options.delete_existing_points:
                    client.delete_points_by_filter(document_filter(document.document_id))
                client.upsert_points(points, batch_size=self.options.qdrant_batch_size)
            write_index_manifest(
                artifact_root=self.options.artifact_root,
                document=document,
                collection=index_identity.collection,
                index_version=index_identity.index_version,
                point_counts=counts,
                point_schema_version=index_identity.point_schema_version,
                embedding_model=embedding_model.name,
                embedding_dimensions=embedding_model.dimensions,
            )
        document = self.registry.update_document(
            document,
            status="indexed",
            active_collection=index_identity.collection,
            active_index_version=index_identity.index_version,
            last_error_code=None,
            last_error_message=None,
        )
        self.registry.update_job(
            job,
            stage="qdrant_index",
            status="running",
            metadata={
                "collection": index_identity.collection,
                "index_version": index_identity.index_version,
                "point_counts": counts,
                "points_total": sum(counts.values()),
            },
        )
        return document, counts

    def verify_retrieval(
        self,
        document: IngestionDocument,
        point_counts: Dict[str, int],
        job: IngestionJob,
    ) -> IngestionDocument:
        self.registry.update_job(job, stage="retrieval_verify", status="running")
        if self.options.dry_run:
            return self.registry.update_document(document, status="retrieval_verified")
        total_points = 0
        payloads: list[dict[str, Any]] = []
        with QdrantRestClient(self.runtime.qdrant_config()) as client:
            payloads = client.scroll_payloads(document_filter(document.document_id), limit=256)
        total_points = len(payloads)
        if total_points < self.options.verify_min_points:
            raise RuntimeError(f"retrieval verification failed: no Qdrant points for {document.document_id}")
        has_context = any(payload.get("point_type") in {"rag_chunk", "table_record"} for payload in payloads)
        if not has_context:
            raise RuntimeError(f"retrieval verification failed: no context points for {document.document_id}")
        source_pdfs = {payload.get("source_pdf") for payload in payloads if payload.get("source_pdf")}
        if document.source_pdf not in source_pdfs:
            raise RuntimeError(f"retrieval verification failed: source_pdf mismatch for {document.document_id}")
        verified_status = "searchable"
        if point_counts.get("evidence_record", 0) == 0:
            verified_status = "needs_review"
        document = self.registry.update_document(document, status=verified_status)
        self.registry.update_job(
            job,
            stage="retrieval_verify",
            status="running",
            metadata={"retrieval_verified_points": total_points, "document_status": verified_status},
        )
        return document

    def mineru_artifact_root(self, document: IngestionDocument, task_id: str) -> Path:
        return self.options.artifact_root / "mineru" / document.document_id / task_id


def build_embedding_model(runtime: RuntimeServices) -> HashEmbeddingModel | SentenceEmbeddingModel:
    return runtime.embedding_model()


def build_index_version(embedding_model: HashEmbeddingModel | SentenceEmbeddingModel) -> str:
    return build_model_index_version(embedding_model)


def parser_version(runtime: RuntimeServices) -> str:
    parser = runtime.config.document_parser
    return f"{parser.provider}_{parser.network_scope}"


def document_filter(document_id: str) -> Dict[str, Any]:
    return {"must": [{"key": "document_id", "match": {"value": document_id}}]}


def classify_failure(stage: str) -> tuple[str, str]:
    if stage == "mineru_parse":
        return "failed_mineru", "failed_mineru"
    if stage == "rag_build":
        return "failed_rag_build", "failed_rag_build"
    if stage == "evidence_extract":
        return "failed_evidence", "failed_evidence"
    if stage == "qdrant_index":
        return "failed_indexing", "failed_indexing"
    if stage == "retrieval_verify":
        return "failed_retrieval_verification", "failed_retrieval_verification"
    return "failed_upload_validation", "failed_upload_validation"


def require_existing_path(value: Optional[str], field_name: str) -> Path:
    if not value:
        raise ValueError(f"{field_name} is required")
    path = Path(value)
    if not path.exists():
        raise FileNotFoundError(path)
    return path


def resolve_document_pdf_path(value: str) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    return path.resolve()


def resolve_existing_artifact_dir(document: IngestionDocument) -> Optional[Path]:
    if not document.active_artifact_dir:
        return None
    path = Path(document.active_artifact_dir)
    if not path.is_dir():
        return None
    try:
        return find_mineru_auto_dir(path)
    except (FileNotFoundError, ValueError):
        return None


def extract_zip_safe(zip_path: Path, target_dir: Path) -> None:
    target_dir.mkdir(parents=True, exist_ok=True)
    target_root = target_dir.resolve()
    with zipfile.ZipFile(zip_path) as archive:
        for member in archive.infolist():
            destination = (target_dir / member.filename).resolve()
            if not str(destination).startswith(str(target_root)):
                raise ValueError(f"unsafe zip member path: {member.filename}")
        archive.extractall(target_dir)
    write_extraction_marker(zip_path, target_dir)


def write_extraction_marker(zip_path: Path, target_dir: Path) -> None:
    marker = {
        "zip_path": str(zip_path),
        "target_dir": str(target_dir),
    }
    (target_dir / "extraction_manifest.json").write_text(json.dumps(marker, ensure_ascii=False, indent=2) + "\n")


def write_index_manifest(
    artifact_root: Path,
    document: IngestionDocument,
    collection: str,
    index_version: str,
    point_counts: Dict[str, int],
    point_schema_version: str = POINT_SCHEMA_VERSION,
    embedding_model: Optional[str] = None,
    embedding_dimensions: Optional[int] = None,
) -> Path:
    manifest = {
        "document_id": document.document_id,
        "source_pdf": document.source_pdf,
        "sha256": document.sha256,
        "collection": collection,
        "index_version": index_version,
        "point_schema_version": point_schema_version,
        "embedding_model": embedding_model,
        "embedding_dimensions": embedding_dimensions,
        "point_counts": point_counts,
        "points_total": sum(point_counts.values()),
    }
    output_dir = artifact_root / "indexing" / safe_identifier(collection, max_length=120)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{safe_identifier(document.document_id, max_length=80)}.json"
    write_json(output_path, manifest)
    return output_path
