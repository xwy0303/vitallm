from __future__ import annotations

import argparse
import sys
from pathlib import Path

from enzyme_recommender.rag.embedding import HashEmbeddingConfig, HashEmbeddingModel
from enzyme_recommender.rag.qdrant import (
    QdrantConfig,
    QdrantRestClient,
    build_index_points,
    point_type_counts,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Index RAG inputs and evidence records into a local Qdrant collection.")
    parser.add_argument("--rag-input-dir", required=True, type=Path)
    parser.add_argument("--evidence-dir", default=None, type=Path)
    parser.add_argument("--qdrant-url", default="http://127.0.0.1:6333")
    parser.add_argument("--collection", default="enzyme_immobilization")
    parser.add_argument("--dimensions", default=384, type=int)
    parser.add_argument("--batch-size", default=64, type=int)
    parser.add_argument("--recreate", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    embedding_model = HashEmbeddingModel(HashEmbeddingConfig(dimensions=args.dimensions))
    points = build_index_points(
        rag_input_dir=args.rag_input_dir,
        evidence_dir=args.evidence_dir,
        embedding_model=embedding_model,
    )

    counts = point_type_counts(points)
    print(f"Prepared points: total={len(points)} counts={counts}")
    print(f"Embedding model: {embedding_model.name}")

    if args.dry_run:
        print("Dry run complete; Qdrant was not modified.")
        return

    config = QdrantConfig(url=args.qdrant_url, collection=args.collection)
    try:
        with QdrantRestClient(config) as client:
            client.ensure_collection(vector_size=embedding_model.dimensions, recreate=args.recreate)
            client.upsert_points(points, batch_size=args.batch_size)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc

    print(f"Indexed {len(points)} points into {args.qdrant_url} collection={args.collection}")


if __name__ == "__main__":
    main()
