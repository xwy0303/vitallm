from __future__ import annotations

import argparse
from pathlib import Path

from enzyme_recommender.rag import build_rag_inputs
from enzyme_recommender.rag.artifacts import write_json, write_jsonl


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build clean RAG input JSONL files from a MinerU artifact directory."
    )
    parser.add_argument(
        "--artifact-dir",
        required=True,
        type=Path,
        help="MinerU auto directory or a parent directory containing *_content_list.json.",
    )
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--document-id", default=None)
    parser.add_argument("--source-pdf", default=None)
    parser.add_argument("--max-chars", default=1200, type=int)
    parser.add_argument("--min-chars", default=80, type=int)
    parser.add_argument("--artifact-root", default=Path("artifacts"), type=Path)
    parser.add_argument("--fallback-manifest", default=None, type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    outputs = build_rag_inputs(
        artifact_dir=args.artifact_dir,
        source_pdf=args.source_pdf,
        document_id=args.document_id,
        max_chars=args.max_chars,
        min_chars=args.min_chars,
        artifact_root=args.artifact_root,
        fallback_manifest_path=args.fallback_manifest,
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_json(args.output_dir / "document_manifest.json", outputs["manifest"])
    write_jsonl(args.output_dir / "rag_chunks.jsonl", outputs["rag_chunks"])
    write_jsonl(args.output_dir / "table_records.jsonl", outputs["table_records"])
    write_jsonl(args.output_dir / "extraction_candidates.jsonl", outputs["extraction_candidates"])

    counts = outputs["manifest"]["counts"]
    print(f"Wrote {args.output_dir}")
    print(
        "Counts: "
        f"chunks={counts['rag_chunks']} "
        f"tables={counts['table_records']} "
        f"candidates={counts['extraction_candidates']} "
        f"pages={counts['pages']}"
    )
    qa_gate = outputs["manifest"].get("qa_gate", {})
    print(f"QA gate: status={qa_gate.get('status')} flags={qa_gate.get('flag_counts', {})}")


if __name__ == "__main__":
    main()
