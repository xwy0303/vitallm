from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import sys

PROJECT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from enzyme_recommender.ingestion.registry import IngestionRegistry


INDEXED_TERMINAL_STATUSES = {"searchable", "needs_review"}
ACTIVE_JOB_STATUSES = {"queued", "running"}


@dataclass(frozen=True)
class CorpusRegistrationSummary:
    batch_id: str
    pdfs: int
    registered: int
    duplicates: int
    jobs_created: int
    active_jobs_skipped: int
    document_ids: list[str]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Register a directory of source PDFs into the ingestion registry.")
    parser.add_argument("--pdf-dir", default=PROJECT_DIR / "MOF固定化脂肪酶文献调研", type=Path)
    parser.add_argument("--artifact-root", default=PROJECT_DIR / "artifacts", type=Path)
    parser.add_argument("--uploaded-by", default="historical_corpus")
    parser.add_argument("--queue-jobs", action="store_true")
    parser.add_argument("--limit", default=None, type=int)
    parser.add_argument(
        "--pdf-name",
        action="append",
        default=[],
        help="Register only this PDF stem or filename. Repeat for multiple PDFs.",
    )
    parser.add_argument(
        "--requeue-indexed",
        action="store_true",
        help="Queue jobs even when the latest document state is already searchable/needs_review.",
    )
    parser.add_argument(
        "--target-collection",
        default=None,
        help="Skip terminal documents only when their active_collection already matches this collection.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    pdf_paths = select_pdf_paths(args.pdf_dir, args.pdf_name)
    if args.limit is not None:
        pdf_paths = pdf_paths[: args.limit]
    if not pdf_paths:
        raise SystemExit(f"No PDF files found under {args.pdf_dir}")

    summary = register_pdf_corpus(
        pdf_paths=pdf_paths,
        artifact_root=args.artifact_root,
        uploaded_by=args.uploaded_by,
        queue_jobs=args.queue_jobs,
        requeue_indexed=args.requeue_indexed,
        target_collection=args.target_collection,
    )
    print(f"batch_id={summary.batch_id}")
    print(
        f"pdfs={summary.pdfs} registered={summary.registered} duplicates={summary.duplicates} "
        f"jobs_created={summary.jobs_created} active_jobs_skipped={summary.active_jobs_skipped}"
    )
    print(f"document_ids={','.join(summary.document_ids)}")


def register_pdf_corpus(
    pdf_paths: list[Path],
    artifact_root: Path,
    uploaded_by: str = "historical_corpus",
    queue_jobs: bool = False,
    requeue_indexed: bool = False,
    target_collection: str | None = None,
) -> CorpusRegistrationSummary:
    registry = IngestionRegistry(artifact_root)
    registered = []
    duplicates = 0
    jobs_created = 0
    active_jobs_skipped = 0
    for pdf_path in pdf_paths:
        item = registry.register_pdf_path(pdf_path, uploaded_by=uploaded_by)
        registered.append(item)
        duplicates += int(item.duplicate)
    batch = registry.create_batch(registered, uploaded_by=uploaded_by)

    if queue_jobs:
        queued_document_ids: set[str] = set()
        for item in registered:
            document = registry.get_document(item.document.document_id) or item.document
            if document.document_id in queued_document_ids:
                continue
            if should_skip_terminal_document(document, requeue_indexed, target_collection):
                continue
            if has_active_ingestion_job(registry, document.document_id):
                active_jobs_skipped += 1
                continue
            registry.create_job(
                document,
                metadata={
                    "queued_by": "register_pdf_corpus",
                    "duplicate": item.duplicate,
                    "batch_id": batch.batch_id,
                },
            )
            queued_document_ids.add(document.document_id)
            jobs_created += 1

    return CorpusRegistrationSummary(
        batch_id=batch.batch_id,
        pdfs=len(pdf_paths),
        registered=len(registered),
        duplicates=duplicates,
        jobs_created=jobs_created,
        active_jobs_skipped=active_jobs_skipped,
        document_ids=[item.document.document_id for item in registered],
    )


def select_pdf_paths(pdf_dir: Path, pdf_names: list[str]) -> list[Path]:
    if not pdf_names:
        return sorted(pdf_dir.glob("*.pdf"), key=lambda path: path.name.strip())

    paths: list[Path] = []
    seen: set[Path] = set()
    available = {path.name.strip(): path for path in sorted(pdf_dir.glob("*.pdf"), key=lambda item: item.name.strip())}
    available.update({path.stem.strip(): path for path in sorted(pdf_dir.glob("*.pdf"), key=lambda item: item.name.strip())})
    for raw_name in pdf_names:
        name = raw_name.strip()
        if not name:
            continue
        candidates = [name]
        if not name.lower().endswith(".pdf"):
            candidates.append(f"{name}.pdf")
        path = next((available[candidate] for candidate in candidates if candidate in available), None)
        if path is None:
            raise SystemExit(f"No PDF named {raw_name!r} found under {pdf_dir}")
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        paths.append(path)
    return paths


def has_active_ingestion_job(registry: IngestionRegistry, document_id: str) -> bool:
    return any(job.status in ACTIVE_JOB_STATUSES for job in registry.list_jobs_for_document(document_id))


def should_skip_terminal_document(document, requeue_indexed: bool, target_collection: str | None) -> bool:
    if requeue_indexed or document.current_status not in INDEXED_TERMINAL_STATUSES:
        return False
    if target_collection is None:
        return True
    return document.active_collection == target_collection


if __name__ == "__main__":
    main()
