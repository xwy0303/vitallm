from __future__ import annotations

import argparse
import sys
from pathlib import Path

from enzyme_recommender.recommendation import EnzymeRecommendationRequest, RecommendationService
from enzyme_recommender.runtime import RuntimeServices


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Recommend enzyme immobilization strategies from retrieved evidence.")
    parser.add_argument("enzyme_name")
    parser.add_argument("--config", default=Path("configs/local.yaml"), type=Path)
    parser.add_argument("--objective", default="recommend_best_immobilization_agent")
    parser.add_argument("--application-context", default=None)
    parser.add_argument("--constraint", action="append", default=[])
    parser.add_argument("--collection", default=None, help="Override vector store collection for smoke tests or experiments.")
    parser.add_argument("--top-k", default=None, type=int)
    parser.add_argument("--pretty", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    runtime = RuntimeServices.from_config_file(args.config)
    if args.collection:
        runtime.config.vector_store.collection = args.collection
    service = RecommendationService(runtime)
    try:
        response = service.recommend_by_enzyme(
            EnzymeRecommendationRequest(
                enzyme_name=args.enzyme_name,
                objective=args.objective,
                application_context=args.application_context,
                constraints=args.constraint,
                top_k=args.top_k,
            )
        )
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    print(response.model_dump_json(indent=2 if args.pretty else None))


if __name__ == "__main__":
    main()
