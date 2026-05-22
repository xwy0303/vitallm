from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict

from enzyme_recommender.recommendation import FormulationOptimizationRequest, FormulationOptimizationService
from enzyme_recommender.runtime import RuntimeServices


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Optimize an enzyme immobilization formulation from retrieved evidence.")
    parser.add_argument("enzyme_name")
    parser.add_argument("--formulation", required=True, type=Path, help="JSON file path, or '-' to read JSON from stdin.")
    parser.add_argument("--config", default=Path("configs/local.yaml"), type=Path)
    parser.add_argument("--objective", default="optimize_formulation")
    parser.add_argument("--application-context", default=None)
    parser.add_argument("--constraint", action="append", default=[])
    parser.add_argument("--collection", default=None, help="Override vector store collection for smoke tests or experiments.")
    parser.add_argument("--top-k", default=None, type=int)
    parser.add_argument("--pretty", action="store_true")
    return parser.parse_args()


def load_formulation(path: Path) -> Dict[str, Any]:
    text = sys.stdin.read() if str(path) == "-" else path.read_text(encoding="utf-8")
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError("formulation JSON must be an object")
    return payload


def main() -> None:
    args = parse_args()
    runtime = RuntimeServices.from_config_file(args.config)
    if args.collection:
        runtime.config.vector_store.collection = args.collection
    service = FormulationOptimizationService(runtime)
    try:
        response = service.optimize_formulation(
            FormulationOptimizationRequest(
                enzyme_name=args.enzyme_name,
                user_formulation=load_formulation(args.formulation),
                objective=args.objective,
                application_context=args.application_context,
                constraints=args.constraint,
                top_k=args.top_k,
            )
        )
    except (RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    print(response.model_dump_json(indent=2 if args.pretty else None))


if __name__ == "__main__":
    main()
