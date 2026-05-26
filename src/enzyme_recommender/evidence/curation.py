from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Literal, Optional, Sequence


CURATION_SCHEMA_VERSION = "curated_evidence_v1"
SEVERE_UNCURATABLE_FLAGS = {
    "unrecoverable_page_placeholder",
    "placeholder_page_overlap",
    "table_parse_empty",
}
DecisionAction = Literal["accept", "edit", "reject"]


def append_curation_decision(
    evidence_dir: Path,
    evidence_id: str,
    action: DecisionAction,
    reviewer: str,
    reason: str,
    edited_record: Optional[Dict[str, Any]] = None,
    allow_severe: bool = False,
) -> Dict[str, Any]:
    if action == "edit" and not edited_record:
        raise ValueError("edited_record is required for edit decisions")
    if action != "edit" and edited_record:
        raise ValueError("edited_record is only valid for edit decisions")

    evidence_dir = evidence_dir.expanduser()
    records = load_source_records(evidence_dir)
    source_record = records.get(evidence_id)
    if source_record is None:
        raise ValueError(f"unknown evidence_id: {evidence_id}")
    if action in {"accept", "edit"} and has_uncuratable_flags(source_record) and not allow_severe:
        raise ValueError(
            f"evidence_id {evidence_id} has severe flags {source_record.get('quality_flags')}; "
            "use --allow-severe only after visual/manual verification"
        )

    decision = {
        "decision_id": make_decision_id(evidence_id, action, reviewer, reason, edited_record),
        "curation_schema_version": CURATION_SCHEMA_VERSION,
        "source_evidence_id": evidence_id,
        "action": action,
        "reviewer": reviewer,
        "reason": reason,
        "reviewed_at": utc_now(),
        "edited_record": edited_record,
    }
    append_jsonl(evidence_dir / "curation_decisions.jsonl", decision)
    rebuild_curated_evidence(evidence_dir)
    return decision


def rebuild_curated_evidence(evidence_dir: Path) -> List[Dict[str, Any]]:
    evidence_dir = evidence_dir.expanduser()
    records = load_source_records(evidence_dir)
    decisions = latest_decisions(load_jsonl(evidence_dir / "curation_decisions.jsonl"))
    curated: List[Dict[str, Any]] = []
    for evidence_id, decision in sorted(decisions.items()):
        source_record = records.get(evidence_id)
        if source_record is None:
            continue
        action = decision.get("action")
        if action == "reject":
            continue
        if action == "accept":
            curated.append(make_curated_record(source_record, decision))
        elif action == "edit":
            edited = decision.get("edited_record")
            if not isinstance(edited, dict):
                raise ValueError(f"edit decision missing edited_record for {evidence_id}")
            curated.append(make_curated_record(source_record, decision, edited_record=edited))
    write_jsonl(evidence_dir / "curated_evidence_records.jsonl", curated)
    write_curation_report(evidence_dir, records.values(), decisions.values(), curated)
    return curated


def make_curated_record(
    source_record: Dict[str, Any],
    decision: Dict[str, Any],
    edited_record: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    record = dict(source_record)
    if edited_record:
        record.update(edited_record)
    source_evidence_id = str(source_record.get("evidence_id") or decision.get("source_evidence_id") or "")
    record["source_evidence_id"] = source_evidence_id
    record["evidence_id"] = make_curated_evidence_id(source_evidence_id, decision, edited_record)
    record["candidate_source"] = "curated_evidence"
    record["curation_schema_version"] = CURATION_SCHEMA_VERSION
    record["curation_status"] = str(decision.get("action") or "accepted")
    record["curation_reason"] = decision.get("reason")
    record["reviewed_by"] = decision.get("reviewer")
    record["reviewed_at"] = decision.get("reviewed_at")
    record["quality_flags"] = list(edited_record.get("quality_flags", []) if edited_record else record.get("quality_flags") or [])
    record["qa_flags"] = list(edited_record.get("qa_flags", []) if edited_record else record.get("qa_flags") or [])
    record["review_reasons"] = []
    record["requires_review"] = False
    record["usable_for_ranking"] = True
    record["confidence"] = record.get("confidence") if record.get("confidence") in {"medium", "high"} else "high"
    return record


def load_source_records(evidence_dir: Path) -> Dict[str, Dict[str, Any]]:
    records: Dict[str, Dict[str, Any]] = {}
    for row in load_jsonl(evidence_dir / "evidence_records.jsonl"):
        evidence_id = row.get("evidence_id")
        if evidence_id:
            records[str(evidence_id)] = row
    return records


def latest_decisions(decisions: Sequence[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    latest: Dict[str, Dict[str, Any]] = {}
    for decision in decisions:
        source_id = decision.get("source_evidence_id")
        if not source_id:
            continue
        latest[str(source_id)] = decision
    return latest


def summarize_curation(evidence_root: Path) -> Dict[str, Any]:
    evidence_root = evidence_root.expanduser()
    summary = {
        "documents": 0,
        "source_records": 0,
        "review_queue": 0,
        "decisions": 0,
        "curated_records": 0,
        "by_action": {},
    }
    if not evidence_root.is_dir():
        return summary
    for evidence_dir in sorted(path for path in evidence_root.iterdir() if path.is_dir()):
        summary["documents"] += 1
        summary["source_records"] += count_jsonl(evidence_dir / "evidence_records.jsonl")
        summary["review_queue"] += count_jsonl(evidence_dir / "review_queue.jsonl")
        summary["curated_records"] += count_jsonl(evidence_dir / "curated_evidence_records.jsonl")
        decisions = load_jsonl(evidence_dir / "curation_decisions.jsonl")
        summary["decisions"] += len(decisions)
        for decision in decisions:
            action = str(decision.get("action") or "<missing>")
            summary["by_action"][action] = summary["by_action"].get(action, 0) + 1
    return summary


def write_curation_report(
    evidence_dir: Path,
    source_records: Iterable[Dict[str, Any]],
    decisions: Iterable[Dict[str, Any]],
    curated: Sequence[Dict[str, Any]],
) -> None:
    decision_list = list(decisions)
    source_list = list(source_records)
    by_action: Dict[str, int] = {}
    for decision in decision_list:
        action = str(decision.get("action") or "<missing>")
        by_action[action] = by_action.get(action, 0) + 1
    report = {
        "curation_schema_version": CURATION_SCHEMA_VERSION,
        "source_records": len(source_list),
        "review_required_source_records": sum(1 for record in source_list if record.get("requires_review")),
        "decisions": len(decision_list),
        "curated_records": len(curated),
        "by_action": by_action,
        "notes": [
            "curated_evidence_records.jsonl is the manually reviewed overlay used for ranking.",
            "raw evidence_records.jsonl remains the immutable first-pass extraction output.",
        ],
    }
    (evidence_dir / "curation_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def has_uncuratable_flags(record: Dict[str, Any]) -> bool:
    flags = set(record.get("quality_flags") or []) | set(record.get("qa_flags") or [])
    return bool(flags & SEVERE_UNCURATABLE_FLAGS)


def make_curated_evidence_id(
    source_evidence_id: str,
    decision: Dict[str, Any],
    edited_record: Optional[Dict[str, Any]] = None,
) -> str:
    payload = {
        "source_evidence_id": source_evidence_id,
        "decision_id": decision.get("decision_id"),
        "action": decision.get("action"),
        "edited_record": edited_record,
    }
    digest = hashlib.sha1(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    return f"cur_{digest[:16]}"


def make_decision_id(
    evidence_id: str,
    action: str,
    reviewer: str,
    reason: str,
    edited_record: Optional[Dict[str, Any]],
) -> str:
    payload = {
        "evidence_id": evidence_id,
        "action": action,
        "reviewer": reviewer,
        "reason": reason,
        "edited_record": edited_record,
        "timestamp": utc_now(),
    }
    digest = hashlib.sha1(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    return f"dec_{digest[:16]}"


def count_jsonl(path: Path) -> int:
    return sum(1 for _row in load_jsonl(path))


def load_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.is_file():
        return []
    rows: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            payload = json.loads(line)
            if not isinstance(payload, dict):
                raise ValueError(f"expected JSON object at {path}:{line_number}")
            rows.append(payload)
    return rows


def write_jsonl(path: Path, rows: Sequence[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            json.dump(row, handle, ensure_ascii=False)
            handle.write("\n")


def append_jsonl(path: Path, row: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        json.dump(row, handle, ensure_ascii=False)
        handle.write("\n")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
