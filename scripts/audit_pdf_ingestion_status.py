from __future__ import annotations

import argparse
import json
from pathlib import Path

from enzyme_recommender.ingestion.audit import (
    AuditOptions,
    DEFAULT_GAP_DOCUMENT_IDS,
    audit_ingestion_documents,
    write_audit_csv,
    write_audit_markdown,
)
from enzyme_recommender.rag.qdrant import QdrantConfig
from enzyme_recommender.runtime.config import RuntimeConfig


PROJECT_DIR = Path(__file__).resolve().parent.parent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit PDF ingestion status across registry, fallback artifacts, RAG/evidence artifacts, and Qdrant."
    )
    parser.add_argument("--artifact-root", default=PROJECT_DIR / "artifacts", type=Path)
    parser.add_argument("--config", default=PROJECT_DIR / "configs" / "local.yaml", type=Path)
    parser.add_argument("--document-id", action="append", default=[])
    parser.add_argument("--skip-qdrant", action="store_true", help="Do not query Qdrant; report qdrant_points=unknown.")
    parser.add_argument("--csv-output", default=None, type=Path)
    parser.add_argument("--md-output", default=None, type=Path)
    parser.add_argument("--json", action="store_true", help="Print JSON rows to stdout instead of a compact summary.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    document_ids = args.document_id or DEFAULT_GAP_DOCUMENT_IDS
    qdrant_config = None if args.skip_qdrant else build_qdrant_config(args.config)
    rows = audit_ingestion_documents(
        AuditOptions(
            artifact_root=args.artifact_root,
            document_ids=document_ids,
            qdrant_config=qdrant_config,
        )
    )
    if args.csv_output:
        write_audit_csv(rows, args.csv_output)
    if args.md_output:
        write_audit_markdown(rows, args.md_output)
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(summarize(rows), ensure_ascii=False, indent=2))


def build_qdrant_config(config_path: Path) -> QdrantConfig:
    config = RuntimeConfig.from_file(config_path)
    return QdrantConfig(
        url=config.vector_store.url,
        collection=config.vector_store.collection,
        timeout=config.vector_store.timeout_seconds,
    )


def summarize(rows: list[dict[str, str]]) -> dict[str, object]:
    action_counts: dict[str, int] = {}
    for row in rows:
        action = row["next_action"]
        action_counts[action] = action_counts.get(action, 0) + 1
    return {
        "documents": len(rows),
        "next_action_counts": action_counts,
        "blocked": [row["document_id"] for row in rows if row["next_action"] in {"blocked", "register_source_pdf"}],
    }


if __name__ == "__main__":
    main()
