from __future__ import annotations

import json
from pathlib import Path

from enzyme_recommender.schemas import (
    ExtractionRecord,
    RecommendationInput,
    RecommendationOutput,
)


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "schemas" / "generated"


def write_schema(model, filename: str) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / filename
    with path.open("w", encoding="utf-8") as handle:
        json.dump(model.model_json_schema(), handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(f"Wrote {path.relative_to(ROOT)}")


def main() -> None:
    write_schema(ExtractionRecord, "extraction_record.schema.json")
    write_schema(RecommendationInput, "recommendation_input.schema.json")
    write_schema(RecommendationOutput, "recommendation_output.schema.json")


if __name__ == "__main__":
    main()

