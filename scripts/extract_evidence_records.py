from __future__ import annotations

import argparse
from pathlib import Path

from enzyme_recommender.evidence import extract_evidence_records
from enzyme_recommender.rag.artifacts import write_json, write_jsonl


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract first-pass structured evidence records from RAG input JSONL files."
    )
    parser.add_argument("--input-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    outputs = extract_evidence_records(args.input_dir)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(args.output_dir / "evidence_records.jsonl", outputs["evidence_records"])
    write_jsonl(args.output_dir / "review_queue.jsonl", outputs["review_queue"])
    write_json(args.output_dir / "validation_report.json", outputs["validation_report"])

    report = outputs["validation_report"]
    print(f"Wrote {args.output_dir}")
    print(
        "Counts: "
        f"evidence_records={report['output_counts']['evidence_records']} "
        f"review_queue={report['output_counts']['review_queue']}"
    )


if __name__ == "__main__":
    main()

