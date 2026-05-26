from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict

from enzyme_recommender.evidence.curation import (
    append_curation_decision,
    rebuild_curated_evidence,
    summarize_curation,
)


PROJECT_DIR = Path(__file__).resolve().parent.parent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Manage manual evidence curation decisions and rebuild curated evidence overlays."
    )
    parser.add_argument("--artifact-root", default=PROJECT_DIR / "artifacts", type=Path)
    parser.add_argument("--document-id", help="Document id under artifacts/evidence/<document-id>.")
    parser.add_argument("--evidence-id", help="Source evidence_id from evidence_records.jsonl or review_queue.jsonl.")
    parser.add_argument("--action", choices=["accept", "edit", "reject"])
    parser.add_argument("--reviewer", default="manual")
    parser.add_argument("--reason", default="")
    parser.add_argument("--edit-json", default=None, help="Inline JSON object used when --action edit.")
    parser.add_argument("--edit-file", default=None, type=Path, help="JSON file used when --action edit.")
    parser.add_argument("--allow-severe", action="store_true", help="Allow accept/edit of severe QA flags after visual verification.")
    parser.add_argument("--rebuild", action="store_true", help="Rebuild curated_evidence_records.jsonl from curation_decisions.jsonl.")
    parser.add_argument("--summary", action="store_true", help="Print curation summary for artifacts/evidence.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    evidence_root = args.artifact_root / "evidence"
    if args.summary:
        print(json.dumps(summarize_curation(evidence_root), ensure_ascii=False, indent=2))
        return

    if not args.document_id:
        raise SystemExit("--document-id is required")
    evidence_dir = evidence_root / args.document_id
    if not evidence_dir.is_dir():
        raise SystemExit(f"Evidence directory not found: {evidence_dir}")

    if args.rebuild:
        curated = rebuild_curated_evidence(evidence_dir)
        print(f"rebuilt curated records: document={args.document_id} records={len(curated)}")
        return

    if not args.action or not args.evidence_id:
        raise SystemExit("--action and --evidence-id are required unless --rebuild or --summary is used")
    decision = append_curation_decision(
        evidence_dir=evidence_dir,
        evidence_id=args.evidence_id,
        action=args.action,
        reviewer=args.reviewer,
        reason=args.reason,
        edited_record=load_edit_payload(args),
        allow_severe=args.allow_severe,
    )
    print(json.dumps(decision, ensure_ascii=False, indent=2))


def load_edit_payload(args: argparse.Namespace) -> Dict[str, Any] | None:
    if args.action != "edit":
        return None
    if args.edit_json and args.edit_file:
        raise SystemExit("Use only one of --edit-json or --edit-file")
    if args.edit_file:
        payload = json.loads(args.edit_file.read_text(encoding="utf-8"))
    elif args.edit_json:
        payload = json.loads(args.edit_json)
    else:
        raise SystemExit("--edit-json or --edit-file is required for --action edit")
    if not isinstance(payload, dict):
        raise SystemExit("Edit payload must be a JSON object")
    return payload


if __name__ == "__main__":
    main()
