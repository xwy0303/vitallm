from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict

from enzyme_recommender.rag.qdrant import PAYLOAD_INDEX_FIELDS, QdrantConfig, QdrantRestClient
from enzyme_recommender.runtime.config import RuntimeConfig


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create Qdrant payload indexes used by RAG retrieval filters.")
    parser.add_argument("--config", default=Path("configs/local.yaml"), type=Path)
    parser.add_argument("--qdrant-url", default=None)
    parser.add_argument("--collection", default=None)
    parser.add_argument("--no-wait", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    runtime_config = RuntimeConfig.from_file(args.config)
    qdrant_url = args.qdrant_url or runtime_config.vector_store.url
    collection = args.collection or runtime_config.vector_store.collection
    config = QdrantConfig(
        url=qdrant_url,
        collection=collection,
        timeout=runtime_config.vector_store.timeout_seconds,
    )

    try:
        with QdrantRestClient(config) as client:
            before = client.list_payload_schema()
            client.ensure_payload_indexes(PAYLOAD_INDEX_FIELDS, wait=not args.no_wait)
            after = client.list_payload_schema()
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc

    summary = build_summary(collection, before, after)
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return
    print(f"Collection: {collection}")
    print(f"Created/verified payload indexes: {len(summary['fields'])}")
    for field in summary["fields"]:
        status = "present" if field["present_after"] else "missing"
        print(f"- {field['field_name']}: {field['field_schema']} {status}")


def build_summary(collection: str, before: Dict[str, Any], after: Dict[str, Any]) -> Dict[str, Any]:
    fields = []
    for field_name, field_schema in PAYLOAD_INDEX_FIELDS.items():
        fields.append(
            {
                "field_name": field_name,
                "field_schema": field_schema,
                "present_before": field_name in before,
                "present_after": field_name in after,
                "actual_after": after.get(field_name),
            }
        )
    return {
        "collection": collection,
        "fields": fields,
        "all_present": all(field["present_after"] for field in fields),
    }


if __name__ == "__main__":
    main()
