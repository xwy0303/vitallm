from __future__ import annotations

import argparse
import sys
from pathlib import Path

from enzyme_recommender.rag.embedding import (
    HashEmbeddingConfig,
    HashEmbeddingModel,
    SentenceEmbeddingConfig,
    SentenceEmbeddingModel,
)
from enzyme_recommender.rag.qdrant import (
    QdrantConfig,
    QdrantRestClient,
    build_index_points,
    point_type_counts,
)
from enzyme_recommender.runtime.config import RuntimeConfig


def _build_embedding_model(args: argparse.Namespace) -> HashEmbeddingModel | SentenceEmbeddingModel:
    if args.embedding_provider == "sentence":
        return SentenceEmbeddingModel(
            SentenceEmbeddingConfig(
                model_name=args.embedding_model_name,
                dimensions=args.dimensions,
                device=args.embedding_device,
                cache_folder=args.embedding_cache_folder,
                local_files_only=args.embedding_local_files_only,
            )
        )
    return HashEmbeddingModel(HashEmbeddingConfig(dimensions=args.dimensions))


def _build_embedding_from_config(config_path: Path) -> HashEmbeddingModel | SentenceEmbeddingModel:
    runtime_config = RuntimeConfig.from_file(config_path)
    emb = runtime_config.embedding
    if emb.provider == "sentence":
        return SentenceEmbeddingModel(
            SentenceEmbeddingConfig(
                model_name=emb.model_name,
                dimensions=emb.dimensions,
                device=emb.device,
                cache_folder=emb.cache_folder,
                local_files_only=emb.local_files_only,
            )
        )
    return HashEmbeddingModel(HashEmbeddingConfig(dimensions=emb.dimensions))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Index RAG inputs and evidence records into a local Qdrant collection."
    )
    parser.add_argument("--rag-input-dir", required=True, type=Path)
    parser.add_argument("--evidence-dir", default=None, type=Path)
    parser.add_argument("--qdrant-url", default="http://127.0.0.1:6333")
    parser.add_argument("--collection", default="enzyme_immobilization")
    parser.add_argument("--dimensions", default=768, type=int)
    parser.add_argument("--batch-size", default=64, type=int)
    parser.add_argument("--recreate", action="store_true")
    parser.add_argument("--dry-run", action="store_true")

    emb_group = parser.add_mutually_exclusive_group()
    emb_group.add_argument(
        "--embedding-config",
        type=Path,
        help="Path to runtime config YAML for embedding provider settings.",
    )
    emb_group.add_argument(
        "--embedding-provider",
        default="sentence",
        choices=["hash_v1", "sentence"],
        help="Embedding provider (default: sentence).",
    )
    parser.add_argument("--embedding-model-name", default="BAAI/bge-base-en-v1.5")
    parser.add_argument("--embedding-device", default="mps")
    parser.add_argument("--embedding-cache-folder", default=None)
    parser.add_argument("--embedding-local-files-only", action="store_true")

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.embedding_config:
        embedding_model = _build_embedding_from_config(args.embedding_config)
    else:
        embedding_model = _build_embedding_model(args)

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
