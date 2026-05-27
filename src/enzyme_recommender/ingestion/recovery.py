from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from enzyme_recommender.ingestion.audit import AuditOptions, audit_ingestion_documents
from enzyme_recommender.ingestion.fallback_queue import queue_fallback_ingestion
from enzyme_recommender.ingestion.pipeline import IngestionPipeline, IngestionPipelineOptions
from enzyme_recommender.ingestion.registry import IngestionRegistry
from enzyme_recommender.rag.qdrant import QdrantConfig
from enzyme_recommender.runtime import RuntimeServices


ACTION_TO_STAGE = {
    "run_mineru_original_pdf": "mineru_parse",
    "build_rag_from_artifact": "rag_build",
    "extract_evidence": "evidence_extract",
    "index_only": "qdrant_index",
    "verify_only": "retrieval_verify",
}

EXECUTABLE_ACTIONS = set(ACTION_TO_STAGE) | {"queue_fallback_ingestion", "run_queued_job"}


@dataclass(frozen=True)
class RecoveryOptions:
    artifact_root: Path
    document_ids: List[str]
    runtime: Optional[RuntimeServices] = None
    qdrant_config: Optional[QdrantConfig] = None
    execute: bool = False
    qdrant_batch_size: int = 64
    mineru_timeout_seconds: float = 1800.0
    mineru_interval_seconds: float = 10.0


def recover_ingestion_gaps(options: RecoveryOptions) -> Dict[str, Any]:
    rows = audit_ingestion_documents(
        AuditOptions(
            artifact_root=options.artifact_root,
            document_ids=options.document_ids,
            qdrant_config=options.runtime.qdrant_config() if options.runtime is not None else options.qdrant_config,
        )
    )
    registry = IngestionRegistry(options.artifact_root)
    reports: List[Dict[str, Any]] = []

    for row in rows:
        action = row["next_action"]
        document_id = row["document_id"]
        report: Dict[str, Any] = {
            "document_id": document_id,
            "action": action,
            "executed": False,
            "status": "planned",
        }
        if action == "none":
            report["status"] = "skipped_already_searchable"
        elif action == "wait_for_running_job":
            report["status"] = "waiting_for_running_job"
            report["reason"] = row.get("blocking_reason") or "document already has a running ingestion job"
        elif action not in EXECUTABLE_ACTIONS:
            report["status"] = "blocked"
            report["reason"] = row.get("blocking_reason") or f"action is not executable: {action}"
        elif not options.execute:
            report["status"] = "dry_run"
            report["resume_from_stage"] = ACTION_TO_STAGE.get(action)
        else:
            try:
                if action == "queue_fallback_ingestion":
                    summary = queue_fallback_ingestion(
                        artifact_root=options.artifact_root,
                        document_ids=[document_id],
                        queue_jobs=True,
                    )
                    report["status"] = "queued_fallback_ingestion"
                    report["executed"] = True
                    report["summary"] = summary
                else:
                    if options.runtime is None:
                        raise ValueError("runtime is required to execute ingestion recovery")
                    document = registry.get_document(document_id)
                    if document is None:
                        raise ValueError(f"unknown ingestion document: {document_id}")
                    job = (
                        latest_queued_job(registry, document_id)
                        if action == "run_queued_job"
                        else registry.create_job(
                            document,
                            metadata={"queued_by": "recover_pdf_ingestion_gaps", "action": action},
                        )
                    )
                    if job is None:
                        raise ValueError(f"no queued ingestion job found for {document_id}")
                    pipeline = IngestionPipeline(
                        runtime=options.runtime,
                        registry=registry,
                        options=IngestionPipelineOptions(
                            artifact_root=options.artifact_root,
                            poll_timeout_seconds=options.mineru_timeout_seconds,
                            poll_interval_seconds=options.mineru_interval_seconds,
                            qdrant_batch_size=options.qdrant_batch_size,
                        ),
                    )
                    result = pipeline.run_document(
                        document_id,
                        job=job,
                        resume_from_stage=ACTION_TO_STAGE.get(action),
                    )
                    report["status"] = "succeeded"
                    report["executed"] = True
                    report["document_status"] = result.document.current_status
                    report["point_counts"] = result.point_counts
            except Exception as exc:
                report["status"] = "failed"
                report["reason"] = str(exc)
        reports.append(report)

    return {
        "execute": options.execute,
        "documents": len(reports),
        "reports": reports,
    }


def filter_document_ids(document_ids: Iterable[str]) -> List[str]:
    return [document_id for document_id in document_ids if document_id]


def latest_queued_job(registry: IngestionRegistry, document_id: str):
    jobs = [job for job in registry.list_jobs_for_document(document_id) if job.status == "queued"]
    if not jobs:
        return None
    return sorted(jobs, key=lambda item: item.created_at)[-1]
