from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from enzyme_recommender.evidence.curation import append_curation_decision, rebuild_curated_evidence


PROJECT_DIR = Path(__file__).resolve().parent.parent
VALID_DECISIONS = {"正确", "需修改", "错误", "不确定"}
REQUIRED_COLUMNS = [
    "任务编号",
    "判定结果",
    "正确的酶/蛋白",
    "正确的载体/材料",
    "正确的固定化方法/条件",
    "正确的指标名",
    "正确的数值",
    "正确的单位",
    "正确原文或表格行",
    "错误原因或备注",
    "标注人",
]
OUTPUT_COLUMNS = [
    "任务编号",
    "PDF文件",
    "页码",
    "内容类型",
    "判定结果",
    "错误类型",
    "错误说明",
    "错误原因或备注",
    "标注人",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import simplified Chinese student review CSV into curation overlays.")
    parser.add_argument("--student-csv", required=True, type=Path)
    parser.add_argument("--mapping", required=True, type=Path)
    parser.add_argument("--artifact-root", default=PROJECT_DIR / "artifacts", type=Path)
    parser.add_argument("--output-dir", default=None, type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--allow-severe", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir = args.output_dir or args.student_csv.parent
    output_dir.mkdir(parents=True, exist_ok=True)
    result = import_student_reviews(
        student_csv=args.student_csv,
        mapping_path=args.mapping,
        artifact_root=args.artifact_root,
        output_dir=output_dir,
        dry_run=args.dry_run,
        allow_severe=args.allow_severe,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


def import_student_reviews(
    student_csv: Path,
    mapping_path: Path,
    artifact_root: Path,
    output_dir: Path,
    dry_run: bool = False,
    allow_severe: bool = False,
) -> Dict[str, Any]:
    mappings = load_mapping(mapping_path)
    rows = read_csv(student_csv)
    validate_columns(rows, student_csv)
    report = {
        "student_csv": str(student_csv),
        "mapping": str(mapping_path),
        "artifact_root": str(artifact_root),
        "dry_run": dry_run,
        "total_rows": len(rows),
        "accepted": 0,
        "edited": 0,
        "rejected": 0,
        "uncertain": 0,
        "skipped_blank": 0,
        "errors": 0,
        "by_decision": {},
        "documents_rebuilt": [],
    }
    unresolved_rows: List[Dict[str, Any]] = []
    affected_docs = set()
    for row in rows:
        normalized = normalize_student_row(row)
        task_id = normalized.get("任务编号")
        decision = normalized.get("判定结果")
        if not any(normalized.values()):
            report["skipped_blank"] += 1
            continue
        report["by_decision"][decision or "<blank>"] = report["by_decision"].get(decision or "<blank>", 0) + 1
        mapping = mappings.get(task_id or "")
        error = validate_student_decision(normalized, mapping)
        if error:
            report["errors"] += 1
            unresolved_rows.append(unresolved_row(normalized, error))
            continue
        assert mapping is not None
        if decision == "不确定":
            report["uncertain"] += 1
            unresolved_rows.append(unresolved_row(normalized, "学生选择不确定，等待二次复核"))
            continue
        action = {"正确": "accept", "需修改": "edit", "错误": "reject"}[decision]
        edited_record = build_edited_record(mapping, normalized) if action == "edit" else None
        reason = decision_reason(normalized)
        if not dry_run:
            evidence_dir = artifact_root.expanduser() / "evidence" / str(mapping["document_id"])
            append_curation_decision(
                evidence_dir=evidence_dir,
                evidence_id=str(mapping["evidence_id"]),
                action=action,  # type: ignore[arg-type]
                reviewer=str(normalized["标注人"]),
                reason=reason,
                edited_record=edited_record,
                allow_severe=allow_severe,
            )
            affected_docs.add(str(mapping["document_id"]))
        if action == "accept":
            report["accepted"] += 1
        elif action == "edit":
            report["edited"] += 1
        elif action == "reject":
            report["rejected"] += 1
    if not dry_run:
        for document_id in sorted(affected_docs):
            rebuild_curated_evidence(artifact_root.expanduser() / "evidence" / document_id)
        report["documents_rebuilt"] = sorted(affected_docs)
    write_json(output_dir / "student_review_import_report.json", report)
    write_csv(output_dir / "student_review_uncertain_or_error.csv", OUTPUT_COLUMNS, unresolved_rows)
    return report


def validate_student_decision(row: Dict[str, str], mapping: Optional[Dict[str, Any]]) -> Optional[str]:
    task_id = row.get("任务编号", "")
    decision = row.get("判定结果", "")
    reviewer = row.get("标注人", "")
    if not task_id:
        return "任务编号为空"
    if mapping is None:
        return "任务编号不存在于映射表"
    if not mapping.get("evidence_id"):
        return "该任务没有 evidence_id，不能自动回灌"
    if decision not in VALID_DECISIONS:
        return "判定结果必须是：正确 / 需修改 / 错误 / 不确定"
    if not reviewer:
        return "标注人为空"
    if decision == "需修改" and not has_edit_content(row):
        return "判定为需修改，但没有填写任何修正内容"
    if decision == "错误" and not row.get("错误原因或备注"):
        return "判定为错误，但没有填写错误原因或备注"
    return None


def build_edited_record(mapping: Dict[str, Any], row: Dict[str, str]) -> Dict[str, Any]:
    source_row = mapping.get("source_review_row") if isinstance(mapping.get("source_review_row"), dict) else {}
    extracted = parse_jsonish(source_row.get("extracted_json"), default={})
    metrics = parse_jsonish(source_row.get("metrics_json"), default=[])
    if not isinstance(extracted, dict):
        extracted = {}
    if not isinstance(metrics, list):
        metrics = []
    enzyme = row.get("正确的酶/蛋白")
    carrier = row.get("正确的载体/材料")
    condition = row.get("正确的固定化方法/条件")
    if enzyme:
        extracted["enzyme_name"] = enzyme
    if carrier:
        extracted["carrier"] = carrier
    if condition:
        if str(mapping.get("record_type")) == "formulation_condition":
            extracted["operating_conditions"] = condition
        else:
            extracted["immobilization_method"] = condition
    metric = build_metric(row)
    if metric:
        metrics = [metric]
    edited: Dict[str, Any] = {
        "extracted": extracted,
        "metrics": metrics,
        "quality_flags": [],
        "qa_flags": [],
        "review_reasons": [],
        "requires_review": False,
        "usable_for_ranking": True,
        "confidence": "high",
    }
    if row.get("正确原文或表格行"):
        edited["evidence_span"] = row["正确原文或表格行"]
    if mapping.get("record_type"):
        edited["record_type"] = mapping["record_type"]
    return edited


def build_metric(row: Dict[str, str]) -> Optional[Dict[str, Any]]:
    metric_name = row.get("正确的指标名")
    metric_value = row.get("正确的数值")
    metric_unit = row.get("正确的单位")
    if not any([metric_name, metric_value, metric_unit]):
        return None
    metric: Dict[str, Any] = {
        "name": metric_name or "manual_metric",
        "value": parse_number(metric_value) if metric_value else None,
        "unit": metric_unit or None,
        "raw": " ".join(part for part in [metric_name, metric_value, metric_unit] if part),
    }
    return metric


def decision_reason(row: Dict[str, str]) -> str:
    note = row.get("错误原因或备注") or row.get("正确原文或表格行") or ""
    if note:
        return note
    return f"student_review:{row.get('判定结果')}"


def has_edit_content(row: Dict[str, str]) -> bool:
    fields = [
        "正确的酶/蛋白",
        "正确的载体/材料",
        "正确的固定化方法/条件",
        "正确的指标名",
        "正确的数值",
        "正确的单位",
        "正确原文或表格行",
    ]
    return any(row.get(field) for field in fields)


def unresolved_row(row: Dict[str, str], error: str) -> Dict[str, Any]:
    output = {column: row.get(column, "") for column in OUTPUT_COLUMNS}
    output["错误类型"] = "待处理"
    output["错误说明"] = error
    return output


def load_mapping(path: Path) -> Dict[str, Dict[str, Any]]:
    mappings = {}
    for row in load_jsonl(path):
        task_id = str(row.get("task_id") or "")
        if task_id:
            mappings[task_id] = row
    return mappings


def validate_columns(rows: Sequence[Dict[str, str]], path: Path) -> None:
    if not rows:
        return
    missing = [column for column in REQUIRED_COLUMNS if column not in rows[0]]
    if missing:
        raise ValueError(f"student CSV missing columns {missing}: {path}")


def normalize_student_row(row: Dict[str, Any]) -> Dict[str, str]:
    return {str(key): normalize_cell(value) for key, value in row.items()}


def normalize_cell(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def parse_number(value: str) -> Any:
    text = str(value).strip()
    if not text:
        return None
    try:
        number = float(text)
    except ValueError:
        return text
    if number.is_integer():
        return int(number)
    return number


def parse_jsonish(value: Any, default: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if not value:
        return default
    try:
        return json.loads(str(value))
    except json.JSONDecodeError:
        return default


def read_csv(path: Path) -> List[Dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, columns: Sequence[str], rows: Sequence[Dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(columns), extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in columns})


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_jsonl(path: Path) -> List[Dict[str, Any]]:
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


if __name__ == "__main__":
    main()
