from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List

from enzyme_recommender.ingestion.registry import IngestionRegistry, sha256_file, utc_now


PROJECT_DIR = Path(__file__).resolve().parent.parent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Queue page-count-preserving raster/OCR fallback PDFs for ingestion under their original document ids."
    )
    parser.add_argument("--artifact-root", default=PROJECT_DIR / "artifacts", type=Path)
    parser.add_argument("--document-id", action="append", default=[], help="Queue only this fallback document id.")
    parser.add_argument("--queue-jobs", action="store_true", help="Create queued ingestion jobs after updating registry.")
    parser.add_argument("--uploaded-by", default="pdf_raster_fallback")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = queue_fallback_ingestion(
        artifact_root=args.artifact_root,
        document_ids=args.document_id,
        queue_jobs=args.queue_jobs,
        uploaded_by=args.uploaded_by,
        dry_run=args.dry_run,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def queue_fallback_ingestion(
    artifact_root: Path,
    document_ids: Iterable[str] = (),
    queue_jobs: bool = False,
    uploaded_by: str = "pdf_raster_fallback",
    dry_run: bool = False,
) -> Dict[str, Any]:
    registry = IngestionRegistry(artifact_root)
    selected = set(document_ids)
    fallback_root = artifact_root / "pdf_raster_fallback"
    if not fallback_root.is_dir():
        raise FileNotFoundError(fallback_root)

    reports: List[Dict[str, Any]] = []
    jobs_created = 0
    documents_updated = 0
    for manifest_path in sorted(fallback_root.glob("*/fallback_manifest.json")):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        doc_id = str(manifest.get("document_id") or manifest_path.parent.name)
        if selected and doc_id not in selected:
            continue
        report = build_fallback_report(manifest_path, manifest)
        document = registry.get_document(doc_id)
        if document is None:
            report["status"] = "skipped_missing_registry_document"
            reports.append(report)
            continue
        if not report["ready"]:
            report["status"] = "skipped_not_ready"
            reports.append(report)
            continue
        fallback_pdf = Path(report["final_pdf_path"])
        if not fallback_pdf.is_absolute():
            fallback_pdf = (PROJECT_DIR / fallback_pdf).resolve()
        if not fallback_pdf.is_file():
            report["status"] = "skipped_missing_fallback_pdf"
            reports.append(report)
            continue

        updated_document = document.model_copy(
            update={
                "source_pdf": document.source_pdf,
                "original_filename": document.original_filename,
                "sha256": sha256_file(fallback_pdf),
                "size_bytes": fallback_pdf.stat().st_size,
                "page_count": int(manifest.get("expected_pages") or manifest.get("final_pdfinfo_pages") or document.page_count),
                "raw_pdf_path": runtime_portable_path(fallback_pdf),
                "uploaded_by": uploaded_by,
                "current_status": "deduplicated",
                "active_task_id": None,
                "active_artifact_dir": None,
                "active_artifact_version": None,
                "active_rag_dir": None,
                "active_evidence_dir": None,
                "last_error_code": None,
                "last_error_message": None,
                "updated_at": utc_now(),
            }
        )
        report["status"] = "queued_registry_update"
        if not dry_run:
            registry.append_document(updated_document)
            documents_updated += 1
            if queue_jobs and not has_active_job(registry, updated_document.document_id):
                job = registry.create_job(
                    updated_document,
                    metadata={
                        "queued_by": "queue_pdf_fallback_ingestion",
                        "fallback_manifest": str(manifest_path),
                        "placeholder_pages": manifest.get("placeholder_pages") or [],
                    },
                )
                jobs_created += 1
                report["job_id"] = job.job_id
        reports.append(report)

    return {
        "fallback_documents": len(reports),
        "documents_updated": documents_updated,
        "jobs_created": jobs_created,
        "dry_run": dry_run,
        "reports": reports,
    }


def build_fallback_report(manifest_path: Path, manifest: Dict[str, Any]) -> Dict[str, Any]:
    expected_pages = manifest.get("expected_pages")
    final_pages = manifest.get("final_pdfinfo_pages")
    bad_pages = ((manifest.get("final_pdfium_render") or {}).get("bad_pages") or [])
    final_pdf_path = manifest.get("final_pdf_path")
    ready = (
        manifest.get("status") in {"fallback_ready", "fallback_ready_with_placeholders"}
        and expected_pages == final_pages
        and not bad_pages
        and bool(final_pdf_path)
    )
    return {
        "document_id": manifest.get("document_id") or manifest_path.parent.name,
        "manifest_path": str(manifest_path),
        "final_pdf_path": final_pdf_path,
        "expected_pages": expected_pages,
        "final_pdfinfo_pages": final_pages,
        "placeholder_pages": manifest.get("placeholder_pages") or [],
        "ready": ready,
    }


def has_active_job(registry: IngestionRegistry, document_id: str) -> bool:
    return any(job.status in {"queued", "running"} for job in registry.list_jobs_for_document(document_id))


def runtime_portable_path(path: Path) -> str:
    resolved = path.expanduser().resolve()
    try:
        return str(resolved.relative_to(PROJECT_DIR))
    except ValueError:
        return str(resolved)


if __name__ == "__main__":
    main()
