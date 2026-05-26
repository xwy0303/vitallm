from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

from enzyme_recommender.rag.indexing import build_collection_name, build_index_version, embedding_identity_slug
from enzyme_recommender.runtime import RuntimeServices


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate the configured embedding model without touching Qdrant.")
    parser.add_argument("--config", default=Path("configs/local.yaml"), type=Path)
    parser.add_argument("--probe", default="Burkholderia cepacia lipase immobilized on ZIF-8 for biodiesel yield")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    runtime = RuntimeServices.from_config_file(args.config)
    model = runtime.embedding_model()
    try:
        vector = model.embed(args.probe)
    except Exception as exc:
        payload = {
            "status": "failed",
            "config": str(args.config),
            "provider": runtime.config.embedding.provider,
            "model_name": runtime.config.embedding.model_name,
            "local_files_only": runtime.config.embedding.local_files_only,
            "error": str(exc),
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2), file=sys.stderr)
        raise SystemExit(2) from exc

    norm = math.sqrt(sum(value * value for value in vector))
    payload = {
        "status": "ok",
        "config": str(args.config),
        "provider": runtime.config.embedding.provider,
        "model_name": model.name,
        "embedding_slug": embedding_identity_slug(model),
        "dimensions": model.dimensions,
        "vector_length": len(vector),
        "vector_norm": norm,
        "index_version": build_index_version(model),
        "derived_collection": build_collection_name(model),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
