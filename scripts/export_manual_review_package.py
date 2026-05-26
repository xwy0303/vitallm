from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence


PROJECT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_RUNTIME_ARTIFACT_ROOT = Path.home() / "Library/Application Support/Shengji/app/artifacts"
DEFAULT_OUTPUT_DIR = PROJECT_DIR / "reports" / "manual_review_260525"
DEFAULT_PDF_DIR = PROJECT_DIR / "MOF固定化脂肪酶文献调研"

SEVERE_FLAGS = {
    "unrecoverable_page_placeholder",
    "placeholder_page_overlap",
    "table_parse_empty",
}
TABLE_FLAGS = {
    "bad_table_structure",
    "missing_enzyme_cell",
    "rotated_or_wide_table_suspected",
    "suspicious_reference_cell",
    "suspicious_table_yield_gt_100",
    "table_header_suspect",
    "table_ragged_rows",
    "table_too_sparse",
}
METRIC_FLAGS = {
    "suspicious_percent_gt_300",
    "suspicious_table_yield_gt_100",
}

REVIEW_COLUMNS = [
    "priority",
    "item_kind",
    "document_id",
    "source_pdf",
    "pdf_path",
    "page_start_1based",
    "page_end_1based",
    "citation",
    "record_type",
    "evidence_id",
    "source_id",
    "table_id",
    "row_index",
    "section",
    "candidate_source",
    "confidence",
    "quality_flags",
    "qa_flags",
    "qa_status",
    "review_reasons",
    "suggested_action",
    "review_task",
    "evidence_span",
    "text_preview",
    "extracted_json",
    "metrics_json",
    "student_decision",
    "corrected_record_type",
    "corrected_evidence_span",
    "corrected_extracted_json",
    "corrected_metrics_json",
    "reject_reason",
    "reviewer",
    "review_notes",
    "curation_accept_command",
    "curation_reject_command",
    "curation_edit_command_template",
]

SOURCE_QA_COLUMNS = [
    "priority",
    "item_kind",
    "document_id",
    "source_pdf",
    "pdf_path",
    "page_start_1based",
    "page_end_1based",
    "citation",
    "source_id",
    "table_id",
    "section",
    "quality_flags",
    "qa_flags",
    "qa_status",
    "review_reasons",
    "suggested_action",
    "review_task",
    "text_preview",
    "columns_json",
    "rows_preview_json",
    "reviewer",
    "student_decision",
    "review_notes",
]

PLACEHOLDER_COLUMNS = [
    "document_id",
    "source_pdf",
    "page_1based",
    "fallback_pdf",
    "status",
    "suggested_action",
    "review_note",
]
STUDENT_REVIEW_COLUMNS = [
    "任务编号",
    "PDF文件",
    "页码",
    "章节或表格",
    "内容类型",
    "需校验内容",
    "机器提取结果",
    "风险提示",
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
STUDENT_CONTENT_TYPES = {
    "enzyme_identity": "酶/蛋白信息",
    "formulation_condition": "固定化/制备条件",
    "immobilization_strategy": "载体/材料信息",
    "performance_metric": "性能结果",
    "table_comparison_row": "表格数据",
}
STUDENT_ALLOWED_CONTENT_TYPES = {
    "表格数据",
    "酶/蛋白信息",
    "载体/材料信息",
    "固定化/制备条件",
    "性能结果",
    "质量问题",
}
STUDENT_DECISIONS = {"正确", "需修改", "错误", "不确定"}
FLAG_HINTS = {
    "bad_table_structure": "表格结构可能损坏",
    "missing_enzyme_cell": "表格行缺少酶/蛋白名称",
    "possible_ocr_duplicate_text": "可能有 OCR 重复文本",
    "suspicious_percent_gt_300": "百分比数值异常大",
    "suspicious_reference_cell": "参考文献单元格可疑",
    "suspicious_table_yield_gt_100": "yield 超过 100%，需核对",
    "table_header_suspect": "表头可能识别错误",
    "table_parse_empty": "表格解析为空",
    "table_ragged_rows": "表格行列不齐",
    "table_too_sparse": "表格内容过稀疏",
    "unrecoverable_page_placeholder": "该页是无法恢复的占位页",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export manual review package for RAG evidence curation.")
    parser.add_argument(
        "--artifact-root",
        type=Path,
        default=DEFAULT_RUNTIME_ARTIFACT_ROOT if DEFAULT_RUNTIME_ARTIFACT_ROOT.exists() else PROJECT_DIR / "artifacts",
    )
    parser.add_argument("--pdf-dir", type=Path, default=DEFAULT_PDF_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--max-preview-chars", type=int, default=900)
    parser.add_argument("--student-friendly", action="store_true", help="Also export simplified Chinese CSVs for student review.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    artifact_root = args.artifact_root.expanduser()
    output_dir = args.output_dir.expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)

    evidence_items = build_evidence_review_items(artifact_root, args.pdf_dir, args.max_preview_chars)
    source_qa_items = build_source_qa_items(artifact_root, args.pdf_dir, args.max_preview_chars)
    placeholder_pages = build_placeholder_pages(artifact_root)
    bad_table_items = [
        row
        for row in evidence_items + source_qa_items
        if row.get("record_type") == "table_comparison_row"
        or row.get("item_kind") == "table_record_qa"
        or overlaps(split_multi(row.get("quality_flags")), TABLE_FLAGS)
    ]

    write_csv(output_dir / "manual_review_items.csv", REVIEW_COLUMNS, evidence_items)
    write_jsonl(output_dir / "manual_review_items.jsonl", evidence_items)
    write_csv(output_dir / "manual_review_priority_p0_p1.csv", REVIEW_COLUMNS, [r for r in evidence_items if r["priority"] in {"P0", "P1"}])
    write_csv(output_dir / "source_qa_items.csv", SOURCE_QA_COLUMNS, source_qa_items)
    write_jsonl(output_dir / "source_qa_items.jsonl", source_qa_items)
    write_csv(output_dir / "bad_table_review.csv", sorted(set(REVIEW_COLUMNS + SOURCE_QA_COLUMNS)), bad_table_items)
    write_csv(output_dir / "placeholder_pages.csv", PLACEHOLDER_COLUMNS, placeholder_pages)
    write_json(output_dir / "manual_edit_template.json", manual_edit_template())

    summary = build_summary(artifact_root, evidence_items, source_qa_items, placeholder_pages, bad_table_items)
    write_json(output_dir / "summary.json", summary)
    write_text(output_dir / "README.md", build_readme(summary))
    write_text(output_dir / "manual_review_sop.md", build_sop(summary))
    if args.student_friendly:
        summary["student_friendly"] = write_student_review_outputs(output_dir, evidence_items)
        write_text(output_dir / "学生标注说明_极简版.md", build_student_instructions(summary["student_friendly"]))
        write_json(output_dir / "summary.json", summary)

    print(json.dumps(summary, ensure_ascii=False, indent=2))


def build_evidence_review_items(artifact_root: Path, pdf_dir: Path, max_preview_chars: int) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for review_path in sorted((artifact_root / "evidence").glob("*/review_queue.jsonl")):
        for record in load_jsonl(review_path):
            flags = sorted(set(record.get("quality_flags") or []) | set(record.get("qa_flags") or []))
            reasons = list(record.get("review_reasons") or [])
            page_start = to_int(record.get("page_start"))
            page_end = to_int(record.get("page_end"))
            document_id = str(record.get("document_id") or review_path.parent.name)
            source_pdf = str(record.get("source_pdf") or f"{document_id}.pdf")
            evidence_id = str(record.get("evidence_id") or "")
            priority = evidence_priority(record, flags, reasons)
            suggested_action, task = suggested_evidence_action(record, flags, reasons)
            extracted = record.get("extracted") if isinstance(record.get("extracted"), dict) else {}
            metrics = record.get("metrics") if isinstance(record.get("metrics"), list) else []
            table_id = extracted.get("table_id") if isinstance(extracted, dict) else None
            row_index = extracted.get("row_index") if isinstance(extracted, dict) else None
            row = {
                "priority": priority,
                "item_kind": "evidence_record",
                "document_id": document_id,
                "source_pdf": source_pdf,
                "pdf_path": str(resolve_pdf_path(pdf_dir, source_pdf)),
                "page_start_1based": one_based(page_start),
                "page_end_1based": one_based(page_end),
                "citation": citation(source_pdf, page_start, page_end),
                "record_type": record.get("record_type") or "",
                "evidence_id": evidence_id,
                "source_id": record.get("source_id") or "",
                "table_id": table_id or "",
                "row_index": row_index if row_index is not None else "",
                "section": record.get("section") or "",
                "candidate_source": record.get("candidate_source") or "",
                "confidence": record.get("confidence") or "",
                "quality_flags": join_multi(flags),
                "qa_flags": join_multi(record.get("qa_flags") or []),
                "qa_status": record.get("qa_status") or "",
                "review_reasons": join_multi(reasons),
                "suggested_action": suggested_action,
                "review_task": task,
                "evidence_span": trim(record.get("evidence_span") or "", max_preview_chars),
                "text_preview": trim(record.get("text") or record.get("evidence_span") or "", max_preview_chars),
                "extracted_json": json_compact(extracted),
                "metrics_json": json_compact(metrics),
                "student_decision": "",
                "corrected_record_type": "",
                "corrected_evidence_span": "",
                "corrected_extracted_json": "",
                "corrected_metrics_json": "",
                "reject_reason": "",
                "reviewer": "",
                "review_notes": "",
                "curation_accept_command": curation_command(document_id, evidence_id, "accept"),
                "curation_reject_command": curation_command(document_id, evidence_id, "reject"),
                "curation_edit_command_template": curation_command(document_id, evidence_id, "edit"),
            }
            rows.append(row)
    return sorted(rows, key=lambda row: (row["priority"], row["document_id"], row["page_start_1based"], row["evidence_id"]))


def build_source_qa_items(artifact_root: Path, pdf_dir: Path, max_preview_chars: int) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    rag_root = artifact_root / "rag_inputs"
    rows.extend(build_rag_source_rows(rag_root, pdf_dir, "rag_chunks.jsonl", "rag_chunk_qa", max_preview_chars))
    rows.extend(build_rag_source_rows(rag_root, pdf_dir, "table_records.jsonl", "table_record_qa", max_preview_chars))
    return sorted(rows, key=lambda row: (row["priority"], row["document_id"], row["page_start_1based"], row["source_id"]))


def build_rag_source_rows(
    rag_root: Path,
    pdf_dir: Path,
    filename: str,
    item_kind: str,
    max_preview_chars: int,
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for path in sorted(rag_root.glob(f"*/{filename}")):
        for record in load_jsonl(path):
            flags = sorted(set(record.get("quality_flags") or []) | set(record.get("qa_flags") or []))
            if not (record.get("requires_review") or flags or record.get("qa_status") == "fail"):
                continue
            document_id = str(record.get("document_id") or path.parent.name)
            source_pdf = str(record.get("source_pdf") or f"{document_id}.pdf")
            page_start = to_int(record.get("page_start", record.get("page_idx")))
            page_end = to_int(record.get("page_end", record.get("page_idx")))
            source_id = str(record.get("chunk_id") or record.get("table_id") or record.get("source_id") or "")
            rows.append(
                {
                    "priority": source_priority(record, flags),
                    "item_kind": item_kind,
                    "document_id": document_id,
                    "source_pdf": source_pdf,
                    "pdf_path": str(resolve_pdf_path(pdf_dir, source_pdf)),
                    "page_start_1based": one_based(page_start),
                    "page_end_1based": one_based(page_end),
                    "citation": citation(source_pdf, page_start, page_end),
                    "source_id": source_id,
                    "table_id": record.get("table_id") or "",
                    "section": record.get("section") or "",
                    "quality_flags": join_multi(flags),
                    "qa_flags": join_multi(record.get("qa_flags") or []),
                    "qa_status": record.get("qa_status") or "",
                    "review_reasons": join_multi(record.get("review_reasons") or []),
                    "suggested_action": suggested_source_action(flags),
                    "review_task": source_review_task(item_kind, flags),
                    "text_preview": trim(record.get("text") or record.get("caption") or "", max_preview_chars),
                    "columns_json": json_compact(record.get("columns") or []),
                    "rows_preview_json": json_compact((record.get("rows") or [])[:5]),
                    "reviewer": "",
                    "student_decision": "",
                    "review_notes": "",
                }
            )
    return rows


def build_placeholder_pages(artifact_root: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for manifest_path in sorted((artifact_root / "pdf_raster_fallback").glob("*/fallback_manifest.json")):
        manifest = load_json(manifest_path)
        document_id = str(manifest.get("document_id") or manifest_path.parent.name)
        final_pdf = manifest.get("final_pdf_path") or manifest.get("output_pdf") or ""
        pages = manifest.get("placeholder_pages") or []
        for page in pages:
            rows.append(
                {
                    "document_id": document_id,
                    "source_pdf": f"{document_id}.pdf",
                    "page_1based": page,
                    "fallback_pdf": str(final_pdf),
                    "status": manifest.get("status") or "",
                    "suggested_action": "reject_or_ignore",
                    "review_note": "placeholder 页不是原始科研内容，不允许 accept/edit 成 usable evidence；如该页内容关键，只能回到原 PDF 重新获取或人工补录并二次审核。",
                }
            )
    return rows


def evidence_priority(record: Dict[str, Any], flags: Sequence[str], reasons: Sequence[str]) -> str:
    flag_set = set(flags)
    reason_set = set(reasons)
    if flag_set & SEVERE_FLAGS:
        return "P0"
    if record.get("record_type") == "table_comparison_row" or flag_set & TABLE_FLAGS:
        return "P1"
    if flag_set & METRIC_FLAGS or reason_set & {"metric_percent_gt_100", "metric_missing_unit"}:
        return "P1"
    if flag_set:
        return "P2"
    return "P3"


def source_priority(record: Dict[str, Any], flags: Sequence[str]) -> str:
    flag_set = set(flags)
    if flag_set & SEVERE_FLAGS:
        return "P0"
    if record.get("qa_status") == "fail" or flag_set & TABLE_FLAGS:
        return "P1"
    if flag_set & METRIC_FLAGS:
        return "P1"
    return "P2"


def suggested_evidence_action(
    record: Dict[str, Any],
    flags: Sequence[str],
    reasons: Sequence[str],
) -> tuple[str, str]:
    flag_set = set(flags)
    reason_set = set(reasons)
    record_type = record.get("record_type")
    if flag_set & SEVERE_FLAGS:
        return (
            "reject",
            "严重来源问题。不要 accept；只有重新找到原 PDF 可验证内容后，才交给工程侧做人工补录。",
        )
    if "missing_enzyme_cell" in flag_set:
        return (
            "edit_or_reject",
            "回到 PDF 表格确认该行 enzyme 是否能由表头/caption/相邻行唯一确定；能确定则 edit，不能确定则 reject。",
        )
    if flag_set & {"suspicious_table_yield_gt_100", "suspicious_percent_gt_300"} or "metric_percent_gt_100" in reason_set:
        return (
            "edit_or_reject",
            "核对 PDF 原值、单位和小数点；确认 OCR 错误则 edit，PDF 本身无法确认则 reject。",
        )
    if "suspicious_reference_cell" in flag_set or "malformed_reference" in reason_set:
        return (
            "edit_or_reject",
            "核对 reference 是否为 This study 或合法文献编号；能修正则 edit，无法定位则 reject。",
        )
    if "possible_ocr_duplicate_text" in flag_set:
        return (
            "accept_or_edit",
            "检查是否重复 OCR 但事实仍正确；字段正确则 accept，字段或数值有错则 edit。",
        )
    if record_type == "table_comparison_row":
        return (
            "edit_or_accept",
            "逐列核对 table row 的 enzyme、support、condition、metric、reference；全部正确才 accept。",
        )
    return (
        "accept_or_edit",
        "核对 evidence_span 与 extracted/metrics 是否和 PDF 一致；正确 accept，字段不全或有 OCR 错则 edit。",
    )


def suggested_source_action(flags: Sequence[str]) -> str:
    flag_set = set(flags)
    if flag_set & SEVERE_FLAGS:
        return "do_not_curate"
    if flag_set & TABLE_FLAGS:
        return "manual_table_check"
    return "manual_source_check"


def source_review_task(item_kind: str, flags: Sequence[str]) -> str:
    flag_set = set(flags)
    if "unrecoverable_page_placeholder" in flag_set:
        return "确认该页是 fallback placeholder；不要从该页录入证据。"
    if item_kind == "table_record_qa":
        return "核对表格 caption、列名、行列错位和单位；如果可恢复事实，记录在 notes，交给工程侧人工补录。"
    return "核对 chunk 是否为 OCR 重复、异常百分比或引用错误；仅作为定位来源，不直接入库。"


def build_summary(
    artifact_root: Path,
    evidence_items: Sequence[Dict[str, Any]],
    source_qa_items: Sequence[Dict[str, Any]],
    placeholder_pages: Sequence[Dict[str, Any]],
    bad_table_items: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "artifact_root": str(artifact_root),
        "output_scope": "manual_review_package",
        "evidence_review_items": len(evidence_items),
        "source_qa_items": len(source_qa_items),
        "total_review_rows": len(evidence_items) + len(source_qa_items),
        "bad_table_rows": len(bad_table_items),
        "placeholder_pages": len(placeholder_pages),
        "evidence_by_priority": dict(sorted(Counter(row["priority"] for row in evidence_items).items())),
        "source_qa_by_priority": dict(sorted(Counter(row["priority"] for row in source_qa_items).items())),
        "evidence_by_record_type": dict(sorted(Counter(row["record_type"] for row in evidence_items).items())),
        "evidence_quality_flags": dict(sorted(counter_from_multi(evidence_items, "quality_flags").items())),
        "source_quality_flags": dict(sorted(counter_from_multi(source_qa_items, "quality_flags").items())),
        "documents_with_evidence_review": len({row["document_id"] for row in evidence_items}),
        "documents_with_source_qa": len({row["document_id"] for row in source_qa_items}),
    }


def write_student_review_outputs(output_dir: Path, evidence_items: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    all_rows, mapping_rows = build_student_review_rows(evidence_items)
    priority_rows = [row for row in all_rows if mapping_priority(row["任务编号"], mapping_rows) in {"P0", "P1"}]
    write_csv(output_dir / "学生标注表_全部.csv", STUDENT_REVIEW_COLUMNS, all_rows)
    write_csv(output_dir / "学生标注表_P0P1.csv", STUDENT_REVIEW_COLUMNS, priority_rows)
    write_jsonl(output_dir / "student_review_mapping.jsonl", mapping_rows)
    return {
        "student_rows": len(all_rows),
        "student_priority_rows": len(priority_rows),
        "mapping_rows": len(mapping_rows),
        "content_types": dict(sorted(Counter(row["内容类型"] for row in all_rows).items())),
        "allowed_decisions": sorted(STUDENT_DECISIONS),
    }


def build_student_review_rows(evidence_items: Sequence[Dict[str, Any]]) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    student_rows: List[Dict[str, Any]] = []
    mapping_rows: List[Dict[str, Any]] = []
    seen_task_ids = set()
    for index, item in enumerate(evidence_items, start=1):
        task_id = make_student_task_id(item, index)
        if task_id in seen_task_ids:
            raise ValueError(f"duplicate student task id: {task_id}")
        seen_task_ids.add(task_id)
        student_rows.append(student_review_row(task_id, item))
        mapping_rows.append(student_mapping_row(task_id, item))
    return student_rows, mapping_rows


def make_student_task_id(item: Dict[str, Any], index: int) -> str:
    document_id = str(item.get("document_id") or "DOC")
    evidence_id = str(item.get("evidence_id") or f"row_{index}")
    suffix = evidence_id.replace("ev_", "")[:8] if evidence_id else f"{index:06d}"
    return f"REV-{document_id}-{suffix}"


def student_review_row(task_id: str, item: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "任务编号": task_id,
        "PDF文件": item.get("source_pdf") or "",
        "页码": display_page_range(item.get("page_start_1based"), item.get("page_end_1based")),
        "章节或表格": display_section_or_table(item),
        "内容类型": student_content_type(item),
        "需校验内容": item.get("evidence_span") or item.get("text_preview") or "",
        "机器提取结果": student_machine_result(item),
        "风险提示": student_risk_hint(item),
        "判定结果": "",
        "正确的酶/蛋白": "",
        "正确的载体/材料": "",
        "正确的固定化方法/条件": "",
        "正确的指标名": "",
        "正确的数值": "",
        "正确的单位": "",
        "正确原文或表格行": "",
        "错误原因或备注": "",
        "标注人": "",
    }


def student_mapping_row(task_id: str, item: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "task_id": task_id,
        "priority": item.get("priority") or "",
        "document_id": item.get("document_id") or "",
        "source_pdf": item.get("source_pdf") or "",
        "page_start_1based": item.get("page_start_1based") or "",
        "page_end_1based": item.get("page_end_1based") or "",
        "record_type": item.get("record_type") or "",
        "evidence_id": item.get("evidence_id") or "",
        "source_id": item.get("source_id") or "",
        "table_id": item.get("table_id") or "",
        "source_review_row": item,
    }


def mapping_priority(task_id: str, mapping_rows: Sequence[Dict[str, Any]]) -> str:
    for row in mapping_rows:
        if row.get("task_id") == task_id:
            return str(row.get("priority") or "")
    return ""


def display_page_range(start: Any, end: Any) -> str:
    start_text = str(start or "").strip()
    end_text = str(end or "").strip()
    if not start_text:
        return ""
    if not end_text or end_text == start_text:
        return start_text
    return f"{start_text}-{end_text}"


def display_section_or_table(item: Dict[str, Any]) -> str:
    table_id = str(item.get("table_id") or "").strip()
    section = str(item.get("section") or "").strip()
    if table_id and section:
        return f"{section}；表格 {table_id}"
    if table_id:
        return f"表格 {table_id}"
    return section


def student_content_type(item: Dict[str, Any]) -> str:
    flags = set(split_multi(item.get("quality_flags"))) | set(split_multi(item.get("qa_flags")))
    if flags & SEVERE_FLAGS:
        return "质量问题"
    record_type = str(item.get("record_type") or "")
    return STUDENT_CONTENT_TYPES.get(record_type, "质量问题")


def student_machine_result(item: Dict[str, Any]) -> str:
    parts = []
    extracted = parse_jsonish(item.get("extracted_json"), default={})
    metrics = parse_jsonish(item.get("metrics_json"), default=[])
    if item.get("record_type"):
        parts.append(f"类型：{student_content_type(item)}")
    if isinstance(extracted, dict):
        extracted_text = extracted_to_chinese_summary(extracted)
        if extracted_text:
            parts.append(f"字段：{extracted_text}")
    if isinstance(metrics, list) and metrics:
        metric_text = metrics_to_chinese_summary(metrics)
        if metric_text:
            parts.append(f"指标：{metric_text}")
    if not parts:
        return "机器未提取出明确字段，请根据原文判断。"
    return "；".join(parts)


def extracted_to_chinese_summary(extracted: Dict[str, Any]) -> str:
    labels = {
        "enzyme_name": "酶/蛋白",
        "carrier": "载体/材料",
        "material_class": "材料类别",
        "immobilization_method": "固定化方法",
        "operating_conditions": "条件",
        "reaction_system": "反应体系",
        "substrate": "底物",
        "acyl_acceptor": "酰基受体",
        "reference": "参考文献",
        "pH": "pH",
        "temperature": "温度",
        "time": "时间",
        "loading": "载量",
    }
    parts = []
    for key, label in labels.items():
        value = extracted.get(key)
        if value not in (None, "", []):
            parts.append(f"{label}={value}")
    return "，".join(parts)


def metrics_to_chinese_summary(metrics: Sequence[Dict[str, Any]]) -> str:
    parts = []
    for metric in metrics:
        if not isinstance(metric, dict):
            continue
        name = metric.get("name") or "指标"
        value = metric.get("value")
        unit = metric.get("unit") or ""
        cycle = metric.get("cycle")
        raw = metric.get("raw")
        text = f"{name}={value}{unit}" if value is not None else str(raw or name)
        if cycle is not None:
            text += f"（{cycle} cycles）"
        parts.append(text)
    return "，".join(parts)


def student_risk_hint(item: Dict[str, Any]) -> str:
    flags = split_multi(item.get("quality_flags")) + split_multi(item.get("qa_flags"))
    hints = [FLAG_HINTS.get(flag, flag) for flag in flags]
    task = str(item.get("review_task") or "").strip()
    if task:
        hints.append(task)
    return "；".join(dict.fromkeys(hints))


def parse_jsonish(value: Any, default: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if not value:
        return default
    try:
        return json.loads(str(value))
    except json.JSONDecodeError:
        return default


def build_student_instructions(summary: Dict[str, Any]) -> str:
    student = summary.get("student_friendly") or {}
    return f"""# 学生标注说明（极简版）

你只需要做一件事：打开 PDF，看对应页码，把表里的“需校验内容”和 PDF 原文/表格对上，然后填写判定。

## 需要填写的文件

优先填写：`学生标注表_P0P1.csv`

如果老师要求全量填写，再填：`学生标注表_全部.csv`

## 判定结果只能填四种

- `正确`：PDF 里能找到，机器提取也没错。
- `需修改`：PDF 里能找到，但机器提取的酶、载体、条件、数值或单位有错。
- `错误`：PDF 里找不到、表格错位无法确认、或这条内容不应该作为证据。
- `不确定`：你无法判断。不要猜。

## 怎么填

1. 打开 `PDF文件`。
2. 跳到 `页码`。
3. 找到 `章节或表格` 附近的内容。
4. 对照 `需校验内容` 和 `机器提取结果`。
5. 填 `判定结果`。
6. 如果填 `需修改`，请尽量填写这些列：
   - `正确的酶/蛋白`
   - `正确的载体/材料`
   - `正确的固定化方法/条件`
   - `正确的指标名`
   - `正确的数值`
   - `正确的单位`
   - `正确原文或表格行`
7. 如果填 `错误`，必须填写 `错误原因或备注`。
8. `标注人` 必须填写你的名字或编号。

## 内容类型说明

- `表格数据`：去 PDF 表格里逐行逐列核对。
- `酶/蛋白信息`：核对 enzyme/protein 名称。
- `载体/材料信息`：核对固定化材料、载体、MOF 等。
- `固定化/制备条件`：核对 pH、温度、时间、浓度、载量等。
- `性能结果`：核对 yield、activity、reuse cycles、stability 等。
- `质量问题`：通常是 OCR、坏表或占位页问题，不确定就填 `不确定`。

## 当前导出统计

- 学生标注总行数：{student.get("student_rows", "")}
- P0/P1 优先标注行数：{student.get("student_priority_rows", "")}
"""


def build_readme(summary: Dict[str, Any]) -> str:
    return f"""# Manual Review Package

生成时间：{summary["generated_at"]}

数据源：`{summary["artifact_root"]}`

## 文件说明

- `manual_review_items.csv`：evidence 级待人工复核主清单，可直接在 Excel/WPS 中填写。
- `manual_review_priority_p0_p1.csv`：高优先级子集，建议先做。
- `manual_review_items.jsonl`：同一清单的机器可读版本。
- `bad_table_review.csv`：表格/坏表相关条目合集。
- `source_qa_items.csv`：chunk/table source 级 QA 条目，主要用于定位上游 OCR/table 问题。
- `placeholder_pages.csv`：fallback placeholder 页清单，原则上不得入库。
- `manual_edit_template.json`：执行 edit curation 时可复制的 JSON 模板。
- `manual_review_sop.md`：给人工复核人员的操作规范。
- `summary.json`：本包统计。

## 当前统计

- evidence review items: {summary["evidence_review_items"]}
- source QA items: {summary["source_qa_items"]}
- total review rows: {summary["total_review_rows"]}
- bad table rows: {summary["bad_table_rows"]}
- placeholder pages: {summary["placeholder_pages"]}

建议先读 `manual_review_sop.md`，再从 `manual_review_priority_p0_p1.csv` 开始。
"""


def build_sop(summary: Dict[str, Any]) -> str:
    return f"""# 生物酶固定化 RAG 人工复核规范

适用对象：0 基础研究生。目标是把机器抽取的可疑 evidence 校正成可追溯、可入库、可用于 RAG ranking 的结构化证据。

## 1. 复核目标

人工复核只做三件事：

1. 判断 evidence 是否与 PDF 原文一致。
2. 修正 OCR、表格错列、单位、小数点、reference、enzyme/support 等字段错误。
3. 对无法确认或来源损坏的条目明确 reject，避免错误事实进入 RAG。

不要做以下事情：

- 不凭常识补全 PDF 中没有写明的信息。
- 不把不同论文、不同表格、不同实验条件混在同一条 evidence 里。
- 不接受 placeholder 页、坏表、无法定位来源的内容。
- 不为了让数据“看起来合理”修改数值；必须以 PDF 可见内容为准。

## 2. 本次复核包范围

- evidence 级待复核：{summary["evidence_review_items"]} 条。
- source QA 条目：{summary["source_qa_items"]} 条。
- 表格相关条目：{summary["bad_table_rows"]} 条。
- placeholder 页：{summary["placeholder_pages"]} 页。

优先级含义：

- `P0`：严重来源问题，通常 reject 或禁止入库。
- `P1`：表格/数值/单位/reference 高风险，必须优先处理。
- `P2`：OCR 重复、轻中度质量问题。
- `P3`：低风险字段确认。

## 3. 需要打开哪些文件

1. `manual_review_sop.md`：本规范。
2. `manual_review_priority_p0_p1.csv`：先处理这个。
3. `manual_review_items.csv`：完整 evidence 复核表。
4. `bad_table_review.csv`：专门查表格错列、坏表。
5. `placeholder_pages.csv`：只用于排除，不用于录入证据。

CSV 可以用 Excel、WPS 或 LibreOffice 打开。打开后不要删除原始列，只填写空白列。

## 4. 每条 evidence 的标准操作

对 `manual_review_items.csv` 的每一行，按顺序做：

1. 看 `priority`，优先做 `P0` 和 `P1`。
2. 打开 `pdf_path`。
3. 跳到 `page_start_1based`；如果有 `page_end_1based`，检查整个页码范围。
4. 在 PDF 中找到 `section`、表格 caption 或 `evidence_span` 对应文字。
5. 对照 `record_type`、`extracted_json`、`metrics_json`。
6. 填写 `student_decision`：
   - `accept`：PDF 可验证，字段和数值都正确。
   - `edit`：PDF 可验证，但字段/数值/单位/reference 有错，需要修正。
   - `reject`：PDF 无法验证、来源是 placeholder、表格错到无法恢复、字段没有依据。
   - `needs_engineer`：你能确认 PDF 有事实，但当前行没有合适 evidence_id 或需要新增人工 evidence。
7. 填写 `reviewer` 和 `review_notes`。不要留空。

## 5. accept / edit / reject 判定标准

### accept

同时满足：

- PDF 中能看到对应文字、表格行或图表说明。
- `evidence_span` 表达的事实没有错。
- `extracted_json` 关键字段正确。
- `metrics_json` 的数值、单位和 cycle 等字段正确。
- 没有 placeholder、坏表、无法解释的异常值。

### edit

适用于：

- OCR 把 `90.0` 识别成 `900.00`。
- 表格行缺 enzyme，但 caption 或表头明确说明整张表都是同一 enzyme。
- reference 应为 `[35]` 或 `This study`，机器抽错。
- unit 缺失，但 PDF 表头或正文明确写了单位。
- `evidence_span` 太乱，但 PDF 里事实清楚。

edit 时至少填写：

- `corrected_evidence_span`
- `corrected_extracted_json`
- `corrected_metrics_json`
- `review_notes`

### reject

出现任一情况即 reject：

- 来源页是 `placeholder_pages.csv` 中的页。
- PDF 对应页没有这条事实。
- 表格行列错位，无法确认哪个数值属于哪个 enzyme/support。
- 数值看似异常，但 PDF 无法确认正确值。
- 证据需要跨多个不相邻段落拼接才成立。

## 6. 不同 record_type 怎么核对

### `enzyme_identity`

检查 enzyme 名称是否准确，例如 `BCL`、`CALB`、`lipase`、`PPL`。不要把 carrier 当 enzyme。

`extracted_json` 示例：

```json
{{"enzyme_name": "BCL"}}
```

### `immobilization_strategy`

检查 carrier/support/material 和 immobilization method。

允许字段：

```json
{{"carrier": "ZIF-8", "material_class": "MOF", "immobilization_method": "adsorption"}}
```

如果只看到 material，但没有 method，不要硬填 method。

### `formulation_condition`

检查 pH、temperature、time、loading、buffer、concentration 等。

示例：

```json
{{"pH": 7.5, "temperature": "25 C", "time": "30 min", "loading": "700 mg"}}
```

单位必须来自 PDF，不要自行换算。

### `performance_metric`

检查 yield、activity、recovery、reuse cycles、stability 等。

`metrics_json` 示例：

```json
[{{"name": "reuse_cycles", "value": 10, "unit": "cycle", "raw": "10 cycles"}}]
```

百分比超过 100 必须重点核对。除 activity recovery 这类确实可能超过 100 的指标外，yield 通常不应超过 100%。

### `table_comparison_row`

必须逐列核对：

1. 表格标题/caption。
2. 列名。
3. 当前行的 enzyme/support/substrate/condition/reference。
4. 数值单位。
5. 是否续表、合并单元格、旋转宽表。

如果 `quality_flags` 有 `missing_enzyme_cell`：

- 表头/caption 明确整张表同一 enzyme：可以 edit。
- 相邻行能唯一推断：在 `review_notes` 说明依据后 edit。
- 不能唯一推断：reject。

## 7. quality_flags 处理规则

- `unrecoverable_page_placeholder`：reject，不得入库。
- `placeholder_page_overlap`：reject，除非重新从原 PDF 可视确认并由工程侧人工补录。
- `table_parse_empty`：reject。
- `bad_table_structure`：先看 PDF；若无法逐列确认，reject。
- `table_ragged_rows`：重点检查列错位。
- `table_header_suspect`：重点检查表头和单位。
- `missing_enzyme_cell`：只在 caption/表头/上下文明确时 edit。
- `suspicious_table_yield_gt_100`：核对小数点和单位；不能确认则 reject。
- `suspicious_percent_gt_300`：核对是否 OCR 错误或 activity recovery；不能确认则 reject。
- `possible_ocr_duplicate_text`：如果事实和字段正确，可以 accept。
- `suspicious_reference_cell` / `malformed_reference`：修正 reference 或 reject。

## 8. 表格坏表如何做成人工 evidence

当前系统支持对已有 `evidence_id` 做 `accept/edit/reject`。如果坏表没有生成可用 evidence_id，只出现在 `source_qa_items.csv`：

1. 在 PDF 中确认该表格事实确实存在。
2. 在 `source_qa_items.csv` 填 `student_decision=needs_engineer`。
3. 在 `review_notes` 写清楚：
   - PDF 页码。
   - 表格编号。
   - 表格标题。
   - 应录入的 enzyme/support/condition/metric/reference。
   - 为什么机器表格不能直接用。
4. 不要自己改 `rag_chunks.jsonl`、`table_records.jsonl` 或 `evidence_records.jsonl`。

工程侧随后会把这些 notes 转成 curated evidence 或专门的人工 evidence overlay。

## 9. 复核完成后交付什么

每位复核人员交付：

1. 填好的 CSV。
2. 如果有 edit，提供对应修正 JSON 或在 CSV 的 corrected 字段填完整 JSON。
3. 所有 reject 必须写 `reject_reason`。
4. 所有 `needs_engineer` 必须写清楚人工补录依据。

## 10. 工程侧回灌命令

accept 示例：

```bash
PYTHONPATH=src .venv/bin/python scripts/curate_evidence.py \\
  --artifact-root artifacts \\
  --document-id A11 \\
  --evidence-id ev_xxx \\
  --action accept \\
  --reviewer reviewer_name \\
  --reason "verified against PDF page"
```

reject 示例：

```bash
PYTHONPATH=src .venv/bin/python scripts/curate_evidence.py \\
  --artifact-root artifacts \\
  --document-id A11 \\
  --evidence-id ev_xxx \\
  --action reject \\
  --reviewer reviewer_name \\
  --reason "table row cannot be verified"
```

edit 示例：

```bash
PYTHONPATH=src .venv/bin/python scripts/curate_evidence.py \\
  --artifact-root artifacts \\
  --document-id A11 \\
  --evidence-id ev_xxx \\
  --action edit \\
  --edit-file reports/manual_review_260525/manual_edit_template.json \\
  --reviewer reviewer_name \\
  --reason "corrected OCR value after PDF check"
```

严重 flags 默认不能 accept/edit。只有重新视觉确认后，工程侧才可加 `--allow-severe`。

## 11. 最低质控要求

- 每条 `P0/P1` 至少由 1 人复核。
- 表格相关 `P1` 建议 10% 抽样双人复核。
- 两人结论冲突时，以 reject 或 needs_engineer 为默认保守结论。
- 不确定就不要入库。
"""


def manual_edit_template() -> Dict[str, Any]:
    return {
        "record_type": "table_comparison_row",
        "evidence_span": "Replace with verified sentence or table row text from PDF.",
        "extracted": {
            "enzyme_name": "",
            "carrier": "",
            "substrate": "",
            "operating_conditions": "",
            "reaction_system": "",
            "acyl_acceptor": "",
            "reference": "",
        },
        "metrics": [
            {
                "name": "",
                "value": None,
                "unit": "",
                "raw": "",
            }
        ],
        "quality_flags": [],
        "qa_flags": [],
        "confidence": "high",
    }


def curation_command(document_id: str, evidence_id: str, action: str) -> str:
    base = (
        "PYTHONPATH=src .venv/bin/python scripts/curate_evidence.py "
        f"--artifact-root artifacts --document-id {document_id} --evidence-id {evidence_id} "
        f"--action {action} --reviewer <reviewer> --reason \"<reason>\""
    )
    if action == "edit":
        return base + " --edit-file reports/manual_review_260525/manual_edit_template.json"
    return base


def write_csv(path: Path, columns: Sequence[str], rows: Sequence[Dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(columns), extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in columns})


def write_jsonl(path: Path, rows: Sequence[Dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            handle.write("\n")


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


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


def resolve_pdf_path(pdf_dir: Path, source_pdf: str) -> Path:
    candidate = pdf_dir / source_pdf
    if candidate.exists():
        return candidate.resolve()
    runtime_candidate = PROJECT_DIR / "MOF固定化脂肪酶文献调研" / source_pdf
    return runtime_candidate.resolve()


def citation(source_pdf: str, page_start: Optional[int], page_end: Optional[int]) -> str:
    if page_start is None:
        return source_pdf
    start = page_start + 1
    end = page_end + 1 if page_end is not None else start
    if end == start:
        return f"{source_pdf}:p{start}"
    return f"{source_pdf}:p{start}-p{end}"


def one_based(value: Optional[int]) -> str:
    return "" if value is None else str(value + 1)


def to_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def trim(value: Any, max_chars: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3] + "..."


def json_compact(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def join_multi(values: Iterable[Any]) -> str:
    return ";".join(str(value) for value in values if str(value))


def split_multi(value: Any) -> List[str]:
    if not value:
        return []
    return [item for item in str(value).split(";") if item]


def overlaps(values: Iterable[str], expected: Iterable[str]) -> bool:
    return bool(set(values) & set(expected))


def counter_from_multi(rows: Sequence[Dict[str, Any]], field: str) -> Counter:
    counter: Counter = Counter()
    for row in rows:
        counter.update(split_multi(row.get(field)))
    return counter


if __name__ == "__main__":
    main()
