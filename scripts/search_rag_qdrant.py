from __future__ import annotations

import argparse
import json
from typing import Any, Dict, List

from enzyme_recommender.rag.embedding import HashEmbeddingConfig, HashEmbeddingModel
from enzyme_recommender.rag.qdrant import QdrantConfig, QdrantRestClient


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Search a local Qdrant RAG collection.")
    parser.add_argument("query")
    parser.add_argument("--qdrant-url", default="http://127.0.0.1:6333")
    parser.add_argument("--collection", default="enzyme_immobilization")
    parser.add_argument("--dimensions", default=384, type=int)
    parser.add_argument("--top-k", default=8, type=int)
    parser.add_argument("--point-type", default=None, choices=["rag_chunk", "table_record", "evidence_record"])
    parser.add_argument("--usable-only", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    embedding_model = HashEmbeddingModel(HashEmbeddingConfig(dimensions=args.dimensions))
    query_filter = build_filter(point_type=args.point_type, usable_only=args.usable_only)

    config = QdrantConfig(url=args.qdrant_url, collection=args.collection)
    with QdrantRestClient(config) as client:
        results = client.search(
            vector=embedding_model.embed(args.query),
            top_k=args.top_k,
            query_filter=query_filter,
        )

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return

    for index, result in enumerate(results, start=1):
        payload = result.get("payload") or {}
        score = result.get("score")
        print(f"{index}. score={score:.4f} type={payload.get('point_type')} id={payload.get('source_id')}")
        print(f"   citation={payload.get('citation')} usable={payload.get('usable_for_ranking')}")
        if payload.get("record_type"):
            print(f"   record_type={payload.get('record_type')} confidence={payload.get('confidence')}")
        if payload.get("quality_flags"):
            print(f"   quality_flags={payload.get('quality_flags')}")
        text = str(payload.get("text") or "").replace("\n", " ")
        print(f"   text={text[:260]}")


def build_filter(point_type: str | None, usable_only: bool) -> Dict[str, Any] | None:
    must: List[Dict[str, Any]] = []
    if point_type:
        must.append({"key": "point_type", "match": {"value": point_type}})
    if usable_only:
        must.append({"key": "usable_for_ranking", "match": {"value": True}})
    if not must:
        return None
    return {"must": must}


if __name__ == "__main__":
    main()
