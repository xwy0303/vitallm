from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from enzyme_recommender.ingestion.pipeline import IngestionPipeline, IngestionPipelineOptions
from enzyme_recommender.ingestion.registry import IngestionRegistry
from enzyme_recommender.rag.indexing import resolve_collection_name
from enzyme_recommender.runtime import RuntimeServices


PROJECT_DIR = Path(__file__).resolve().parent.parent
INDEXED_TERMINAL_STATUSES = {"searchable", "needs_review"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Process queued PDF ingestion jobs: MinerU -> RAG inputs -> evidence -> Qdrant -> retrieval verification."
    )
    parser.add_argument("--config", default=PROJECT_DIR / "configs" / "local.yaml", type=Path)
    parser.add_argument("--artifact-root", default=PROJECT_DIR / "artifacts", type=Path)
    parser.add_argument("--document-id", default=None)
    parser.add_argument("--once", action="store_true", help="Process at most one queued job and exit.")
    parser.add_argument("--until-empty", action="store_true", help="Exit after all currently queued jobs are processed.")
    parser.add_argument("--max-jobs", default=None, type=int, help="Process at most this many queued jobs.")
    parser.add_argument("--collection", default=None, help="Override vector store collection for this worker run.")
    parser.add_argument("--poll-seconds", default=10.0, type=float)
    parser.add_argument("--mineru-timeout-seconds", default=1800.0, type=float)
    parser.add_argument("--mineru-interval-seconds", default=10.0, type=float)
    parser.add_argument("--qdrant-batch-size", default=64, type=int)
    parser.add_argument("--reindex-only", action="store_true")
    parser.add_argument(
        "--reuse-mineru-artifacts",
        action="store_true",
        help="Reuse active MinerU artifacts when present; submit to MinerU only for documents without artifacts.",
    )
    parser.add_argument("--delete-existing-points", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    runtime = RuntimeServices.from_config_file(args.config)
    if args.collection:
        runtime.config.vector_store.collection = resolve_collection_name(
            runtime.embedding_model(),
            collection=args.collection,
        )
    else:
        runtime.config.vector_store.collection = resolve_collection_name(
            runtime.embedding_model(),
            collection=runtime.config.vector_store.collection,
        )
    registry = IngestionRegistry(args.artifact_root)
    options = IngestionPipelineOptions(
        artifact_root=args.artifact_root,
        poll_timeout_seconds=args.mineru_timeout_seconds,
        poll_interval_seconds=args.mineru_interval_seconds,
        qdrant_batch_size=args.qdrant_batch_size,
        skip_mineru=args.reuse_mineru_artifacts,
        reindex_only=args.reindex_only,
        delete_existing_points=args.delete_existing_points,
        dry_run=args.dry_run,
    )
    pipeline = IngestionPipeline(runtime=runtime, registry=registry, options=options)
    processed_jobs = 0

    while True:
        job = next_job(registry, document_id=args.document_id)
        if job is None:
            if args.once or args.document_id or args.until_empty or args.max_jobs is not None:
                print("No queued ingestion job found.")
                return
            time.sleep(args.poll_seconds)
            continue

        document = registry.get_document(job.document_id)
        if document is not None and should_skip_indexed_document(
            document,
            runtime.config.vector_store.collection,
            reindex_only=args.reindex_only,
            delete_existing_points=args.delete_existing_points,
        ):
            skipped = registry.update_job(
                job,
                stage="complete",
                status="skipped",
                metadata={
                    "skip_reason": "document_already_indexed_for_collection",
                    "collection": runtime.config.vector_store.collection,
                },
            )
            print(
                "SKIP "
                f"job={skipped.job_id} "
                f"document={skipped.document_id} "
                f"status={document.current_status} "
                f"collection={runtime.config.vector_store.collection}"
            )
            processed_jobs += 1
            if args.once or args.document_id:
                return
            if args.max_jobs is not None and processed_jobs >= args.max_jobs:
                print(f"Reached --max-jobs={args.max_jobs}.")
                return
            continue

        print(f"Processing job={job.job_id} document={job.document_id} attempt={job.attempt}")
        try:
            result = pipeline.run_document(job.document_id, job=job, reindex_only=args.reindex_only)
        except Exception as exc:
            print(f"FAILED job={job.job_id} document={job.document_id}: {exc}", file=sys.stderr)
            if is_transient_service_error(exc):
                print(
                    "ABORT transient service outage detected; leaving remaining queued jobs untouched.",
                    file=sys.stderr,
                )
                raise SystemExit(2) from exc
            if args.once or args.document_id:
                raise SystemExit(2) from exc
        else:
            print(
                "OK "
                f"job={result.job.job_id} "
                f"document={result.document.document_id} "
                f"status={result.document.current_status} "
                f"points={sum(result.point_counts.values())} "
                f"counts={result.point_counts}"
            )
            processed_jobs += 1
            if args.once or args.document_id:
                return
            if args.max_jobs is not None and processed_jobs >= args.max_jobs:
                print(f"Reached --max-jobs={args.max_jobs}.")
                return


def next_job(registry: IngestionRegistry, document_id: str | None = None):
    jobs = sorted(registry.load_jobs().values(), key=lambda item: item.created_at)
    documents = registry.load_documents()
    for job in jobs:
        if job.status != "queued":
            continue
        if document_id and job.document_id != document_id:
            continue
        if job.document_id not in documents:
            continue
        return job
    return None


def document_is_indexed_for_collection(document, collection: str) -> bool:
    return (
        document.current_status in INDEXED_TERMINAL_STATUSES
        and document.active_collection == collection
    )


def should_skip_indexed_document(
    document,
    collection: str,
    reindex_only: bool = False,
    delete_existing_points: bool = False,
) -> bool:
    if reindex_only or delete_existing_points:
        return False
    return document_is_indexed_for_collection(document, collection)


def is_transient_service_error(exc: Exception) -> bool:
    message = str(exc)
    return (
        "Connection refused" in message
        or "cannot connect to Qdrant" in message
        or "cannot connect to MinerU" in message
        or "[Errno 61]" in message
    )


if __name__ == "__main__":
    main()
