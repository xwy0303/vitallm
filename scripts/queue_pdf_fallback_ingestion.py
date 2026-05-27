from __future__ import annotations

import argparse
import json
from pathlib import Path

from enzyme_recommender.ingestion.fallback_queue import queue_fallback_ingestion


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
        project_dir=PROJECT_DIR,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
