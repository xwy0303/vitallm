from __future__ import annotations

import argparse
import json
from pathlib import Path

from enzyme_recommender.ingestion.audit import DEFAULT_GAP_DOCUMENT_IDS
from enzyme_recommender.ingestion.recovery import RecoveryOptions, recover_ingestion_gaps
from enzyme_recommender.rag.qdrant import QdrantConfig
from enzyme_recommender.runtime import RuntimeServices
from enzyme_recommender.runtime.config import RuntimeConfig


PROJECT_DIR = Path(__file__).resolve().parent.parent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Recover missing PDF ingestion stages without rerunning already completed upstream work."
    )
    parser.add_argument("--artifact-root", default=PROJECT_DIR / "artifacts", type=Path)
    parser.add_argument("--config", default=PROJECT_DIR / "configs" / "local.yaml", type=Path)
    parser.add_argument("--document-id", action="append", default=[])
    parser.add_argument("--execute", action="store_true", help="Actually queue or run recovery actions. Default is dry-run.")
    parser.add_argument("--qdrant-batch-size", default=64, type=int)
    parser.add_argument("--mineru-timeout-seconds", default=1800.0, type=float)
    parser.add_argument("--mineru-interval-seconds", default=10.0, type=float)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    runtime = RuntimeServices.from_config_file(args.config) if args.execute else None
    qdrant_config = None if args.execute else build_qdrant_config(args.config)
    document_ids = args.document_id or DEFAULT_GAP_DOCUMENT_IDS
    summary = recover_ingestion_gaps(
        RecoveryOptions(
            artifact_root=args.artifact_root,
            document_ids=document_ids,
            runtime=runtime,
            qdrant_config=qdrant_config,
            execute=args.execute,
            qdrant_batch_size=args.qdrant_batch_size,
            mineru_timeout_seconds=args.mineru_timeout_seconds,
            mineru_interval_seconds=args.mineru_interval_seconds,
        )
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def build_qdrant_config(config_path: Path) -> QdrantConfig:
    config = RuntimeConfig.from_file(config_path)
    return QdrantConfig(
        url=config.vector_store.url,
        collection=config.vector_store.collection,
        timeout=config.vector_store.timeout_seconds,
    )


if __name__ == "__main__":
    main()
