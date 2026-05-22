from __future__ import annotations

import argparse
import sys

from enzyme_recommender.rag.embedding import HashEmbeddingConfig, HashEmbeddingModel
from enzyme_recommender.rag.qdrant import QdrantConfig
from enzyme_recommender.rag.retrieval import EvidenceRetriever


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
    parser.add_argument("--context", action="store_true", help="Print compact LLM-ready retrieval context.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    embedding_model = HashEmbeddingModel(HashEmbeddingConfig(dimensions=args.dimensions))
    retriever = EvidenceRetriever(
        QdrantConfig(url=args.qdrant_url, collection=args.collection),
        embedding_model=embedding_model,
    )
    try:
        response = retriever.retrieve(
            query=args.query,
            top_k=args.top_k,
            point_type=args.point_type,
            usable_only=args.usable_only,
        )
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc

    if args.json:
        print(response.model_dump_json(indent=2))
        return
    if args.context:
        print(response.context_text())
        return

    for index, hit in enumerate(response.hits, start=1):
        print(f"{index}. score={hit.score:.4f} type={hit.point_type} id={hit.source_id}")
        print(f"   citation={hit.citation} usable={hit.usable_for_ranking}")
        if hit.record_type:
            print(f"   record_type={hit.record_type} confidence={hit.confidence}")
        if hit.quality_flags:
            print(f"   quality_flags={hit.quality_flags}")
        text = hit.text.replace("\n", " ")
        print(f"   text={text[:260]}")


if __name__ == "__main__":
    main()
