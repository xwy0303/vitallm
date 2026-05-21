from __future__ import annotations

import json
from pathlib import Path

from enzyme_recommender.schemas import (
    ExtractionRecord,
    RecommendationInput,
    RecommendationOutput,
)


ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "schemas" / "examples"


def load_json(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def main() -> None:
    cases = [
        (EXAMPLES / "extraction_record.example.json", ExtractionRecord),
        (EXAMPLES / "recommendation_input.example.json", RecommendationInput),
        (EXAMPLES / "recommendation_output.example.json", RecommendationOutput),
    ]
    for path, model in cases:
        model.model_validate(load_json(path))
        print(f"OK {path.relative_to(ROOT)} -> {model.__name__}")


if __name__ == "__main__":
    main()

