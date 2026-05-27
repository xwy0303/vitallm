from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from enzyme_recommender.ingestion.registry import IngestionDocument, IngestionJob, IngestionRegistry
from enzyme_recommender.ingestion.state_machine import TERMINAL_DOCUMENT_STATUSES
from enzyme_recommender.rag.artifacts import find_mineru_auto_dir
from enzyme_recommender.rag.qdrant import QdrantConfig, QdrantRestClient


AUDIT_COLUMNS = [
    "document_id",
    "source_pdf",
    "registry_status",
    "fallback_manifest_exists",
    "fallback_status",
    "placeholder_pages",
    "queued_job",
    "latest_job_stage",
    "latest_job_status",
    "mineru_artifact_exists",
    "rag_inputs_exists",
    "evidence_exists",
    "qdrant_points",
    "searchable",
    "next_action",
    "blocking_reason",
]

DEFAULT_GAP_DOCUMENT_IDS = [
    "A27",
    "A34",
    "A35",
    "A39",
    "A41",
    "A47",
    "A49",
    "A51",
    "A53",
    "A57",
    "A65",
    "A66",
    "A68",
    "A70",
    "A72",
    "A73",
    "A74",
    "A75",
    "A76",
    "A77",
    "A78",
]


@dataclass(frozen=True)
class AuditOptions:
    artifact_root: Path
    document_ids: List[str]
    qdrant_config: Optional[QdrantConfig] = None
    source_pdf_root: Optional[Path] = None


def audit_ingestion_documents(options: AuditOptions) -> List[Dict[str, str]]:
    registry = IngestionRegistry(options.artifact_root)
    documents = registry.load_documents()
    jobs_by_document = group_jobs_by_document(registry.load_jobs().values())
    qdrant_counts = count_qdrant_points(options.qdrant_config, options.document_ids)
    rows: List[Dict[str, str]] = []

    for document_id in options.document_ids:
        document = documents.get(document_id)
        jobs = jobs_by_document.get(document_id, [])
        latest_job = jobs[-1] if jobs else None
        fallback = inspect_fallback_manifest(options.artifact_root, document_id)
        artifact_exists = mineru_artifact_exists(options.artifact_root, document)
        rag_exists = rag_inputs_exist(options.artifact_root, document_id)
        evidence_exists_flag = evidence_exists(options.artifact_root, document_id)
        qdrant_points = qdrant_counts.get(document_id, "unknown")
        has_queued_job = any(job.status == "queued" for job in jobs)
        has_running_job = any(job.status == "running" for job in jobs)
        source_pdf = document.source_pdf if document else f"{document_id}.pdf"
        registry_status = document.current_status if document else "missing_registry_document"
        searchable = str(document is not None and document.current_status in TERMINAL_DOCUMENT_STATUSES).lower()
        next_action, blocking_reason = decide_next_action(
            document=document,
            fallback=fallback,
            artifact_exists=artifact_exists,
            rag_inputs_exists=rag_exists,
            evidence_exists=evidence_exists_flag,
            qdrant_points=qdrant_points,
            has_queued_job=has_queued_job,
            has_running_job=has_running_job,
        )
        rows.append(
            {
                "document_id": document_id,
                "source_pdf": source_pdf,
                "registry_status": registry_status,
                "fallback_manifest_exists": str(fallback["exists"]).lower(),
                "fallback_status": str(fallback.get("status") or ""),
                "placeholder_pages": ",".join(str(page) for page in fallback.get("placeholder_pages") or []),
                "queued_job": str(has_queued_job).lower(),
                "latest_job_stage": latest_job.stage if latest_job else "",
                "latest_job_status": latest_job.status if latest_job else "",
                "mineru_artifact_exists": str(artifact_exists).lower(),
                "rag_inputs_exists": str(rag_exists).lower(),
                "evidence_exists": str(evidence_exists_flag).lower(),
                "qdrant_points": str(qdrant_points),
                "searchable": searchable,
                "next_action": next_action,
                "blocking_reason": blocking_reason,
            }
        )
    return rows


def group_jobs_by_document(jobs: Iterable[IngestionJob]) -> Dict[str, List[IngestionJob]]:
    grouped: Dict[str, List[IngestionJob]] = {}
    for job in sorted(jobs, key=lambda item: item.created_at):
        grouped.setdefault(job.document_id, []).append(job)
    return grouped


def inspect_fallback_manifest(artifact_root: Path, document_id: str) -> Dict[str, Any]:
    path = artifact_root / "pdf_raster_fallback" / document_id / "fallback_manifest.json"
    if not path.is_file():
        return {"exists": False}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"exists": True, "status": "invalid_manifest_json", "path": str(path)}
    if not isinstance(payload, dict):
        return {"exists": True, "status": "invalid_manifest"}
    return {
        "exists": True,
        "path": str(path),
        "status": payload.get("status"),
        "placeholder_pages": payload.get("placeholder_pages") or [],
        "final_pdf_path": payload.get("final_pdf_path"),
    }


def mineru_artifact_exists(artifact_root: Path, document: Optional[IngestionDocument]) -> bool:
    if document is None:
        return False
    candidates: List[Path] = []
    if document.active_artifact_dir:
        candidates.append(Path(document.active_artifact_dir))
    mineru_root = artifact_root / "mineru" / document.document_id
    if mineru_root.is_dir():
        candidates.extend(sorted(path for path in mineru_root.iterdir() if path.is_dir()))
    for candidate in candidates:
        if not candidate.is_dir():
            continue
        try:
            find_mineru_auto_dir(candidate)
            return True
        except (FileNotFoundError, ValueError):
            continue
    return False


def rag_inputs_exist(artifact_root: Path, document_id: str) -> bool:
    root = artifact_root / "rag_inputs" / document_id
    return (root / "document_manifest.json").is_file() and (root / "rag_chunks.jsonl").is_file()


def evidence_exists(artifact_root: Path, document_id: str) -> bool:
    root = artifact_root / "evidence" / document_id
    return (root / "evidence_records.jsonl").is_file()


def count_qdrant_points(
    config: Optional[QdrantConfig],
    document_ids: Iterable[str],
) -> Dict[str, int | str]:
    document_ids = list(document_ids)
    if config is None:
        return {document_id: "unknown" for document_id in document_ids}
    counts: Dict[str, int | str] = {}
    try:
        with QdrantRestClient(config) as client:
            for document_id in document_ids:
                counts[document_id] = client.count_points(
                    {"must": [{"key": "document_id", "match": {"value": document_id}}]},
                )
    except Exception:
        return {document_id: "unknown" for document_id in document_ids}
    return counts


def decide_next_action(
    *,
    document: Optional[IngestionDocument],
    fallback: Dict[str, Any],
    artifact_exists: bool,
    rag_inputs_exists: bool,
    evidence_exists: bool,
    qdrant_points: int | str,
    has_queued_job: bool = False,
    has_running_job: bool = False,
) -> tuple[str, str]:
    if document is None:
        return "register_source_pdf", "document is missing from ingestion registry"
    if document.current_status in TERMINAL_DOCUMENT_STATUSES and qdrant_points not in {0, "0"}:
        return "none", ""
    if has_running_job:
        return "wait_for_running_job", "document already has a running ingestion job"
    if isinstance(qdrant_points, int) and qdrant_points > 0 and not document.current_status in TERMINAL_DOCUMENT_STATUSES:
        return "verify_only", ""
    if evidence_exists:
        return "index_only", ""
    if rag_inputs_exists:
        return "extract_evidence", ""
    if artifact_exists:
        return "build_rag_from_artifact", ""
    if has_queued_job:
        return "run_queued_job", ""
    if document.document_id in {"A47", "A75"}:
        return "run_mineru_original_pdf", "MinerU runtime/model failure should retry original PDF"
    if fallback.get("exists"):
        status = str(fallback.get("status") or "")
        if status in {"fallback_ready", "fallback_ready_with_placeholders"}:
            return "queue_fallback_ingestion", ""
        return "blocked", f"fallback manifest is not ready: {status}"
    return "blocked", "no MinerU artifact, RAG inputs, evidence, or ready fallback manifest"


def write_audit_csv(rows: List[Dict[str, str]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=AUDIT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def write_audit_markdown(rows: List[Dict[str, str]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# PDF Ingestion Gap Status",
        "",
        "`qdrant_points=unknown` means Qdrant was skipped, unavailable, or inaccessible to the audit process.",
        "",
        "| document_id | registry_status | fallback | artifact | rag | evidence | qdrant | searchable | next_action | blocking_reason |",
        "| --- | --- | --- | --- | --- | --- | ---: | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            "| {document_id} | {registry_status} | {fallback_manifest_exists}:{fallback_status} | "
            "{mineru_artifact_exists} | {rag_inputs_exists} | {evidence_exists} | {qdrant_points} | "
            "{searchable} | {next_action} | {blocking_reason} |".format(**row)
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
