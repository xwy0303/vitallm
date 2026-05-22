from __future__ import annotations

import argparse
import math
from pathlib import Path
from typing import Any, Dict, List

from enzyme_recommender.rag.embedding import HashEmbeddingConfig, HashEmbeddingModel
from enzyme_recommender.rag.qdrant import build_index_points


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run an offline retrieval smoke test without Qdrant.")
    parser.add_argument("query")
    parser.add_argument("--rag-input-dir", required=True, type=Path)
    parser.add_argument("--evidence-dir", default=None, type=Path)
    parser.add_argument("--dimensions", default=384, type=int)
    parser.add_argument("--top-k", default=8, type=int)
    parser.add_argument("--point-type", default=None, choices=["rag_chunk", "table_record", "evidence_record"])
    parser.add_argument("--usable-only", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    embedding_model = HashEmbeddingModel(HashEmbeddingConfig(dimensions=args.dimensions))
    points = build_index_points(
        rag_input_dir=args.rag_input_dir,
        evidence_dir=args.evidence_dir,
        embedding_model=embedding_model,
    )
    query_vector = embedding_model.embed(args.query)
    results = []
    for point in points:
        payload = point["payload"]
        if args.point_type and payload.get("point_type") != args.point_type:
            continue
        if args.usable_only and not payload.get("usable_for_ranking"):
            continue
        results.append((cosine(query_vector, point["vector"]), payload))

    results.sort(key=lambda item: item[0], reverse=True)
    for index, (score, payload) in enumerate(results[: args.top_k], start=1):
        print(f"{index}. score={score:.4f} type={payload.get('point_type')} id={payload.get('source_id')}")
        print(f"   citation={payload.get('citation')} usable={payload.get('usable_for_ranking')}")
        if payload.get("record_type"):
            print(f"   record_type={payload.get('record_type')} confidence={payload.get('confidence')}")
        if payload.get("quality_flags"):
            print(f"   quality_flags={payload.get('quality_flags')}")
        text = str(payload.get("text") or "").replace("\n", " ")
        print(f"   text={text[:260]}")


def cosine(left: List[float], right: List[float]) -> float:
    numerator = sum(left_value * right_value for left_value, right_value in zip(left, right))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return numerator / (left_norm * right_norm)


if __name__ == "__main__":
    main()
