from __future__ import annotations

import re
import json
from typing import Any, Dict, List, Optional, Tuple

from enzyme_recommender.rag.retrieval import RetrievalHit, RetrievalResponse


def build_no_answer_text() -> str:
    return "证据不足：当前知识库没有检索到可用于回答该问题的可靠 evidence。"


def build_grounded_answer(
    question: str,
    retrieval: RetrievalResponse,
    paper_process: bool = False,
) -> Optional[str]:
    if not retrieval.hits:
        return build_no_answer_text()
    if paper_process:
        return build_paper_process_answer(question, retrieval)
    return build_general_evidence_answer(question, retrieval)


def build_general_evidence_answer(question: str, retrieval: RetrievalResponse) -> str:
    selected = select_answer_hits(question, retrieval, limit=4)
    if not selected:
        return build_no_answer_text()
    facts = facts_from_hits(selected, retrieval)
    lines = ["基于当前 evidence，可给出如下结论："]
    for item in facts[:5]:
        lines.append(f"- {item['text']} [{item['ref']}]")
    if asks_condition_type(question):
        lines.append("- 需要区分固定化条件、assay 条件和反应/application 条件；不同实验环节的 pH/温度不能合并为一个跨体系结论。")
    lines.append("证据边界：这些结论只适用于已检索到的文献与实验体系，不能外推到全部酶或全部 MOF 体系。")
    return "\n".join(lines)


def build_paper_process_answer(question: str, retrieval: RetrievalResponse) -> str:
    selected = select_answer_hits(question, retrieval, limit=9)
    usable = [hit for hit in selected if is_primary_fact_hit(hit)]
    review = [hit for hit in selected if not is_primary_fact_hit(hit)]
    by_type: Dict[str, List[RetrievalHit]] = {}
    for hit in usable:
        by_type.setdefault(hit.record_type or hit.point_type, []).append(hit)
    label = paper_label(selected)
    strategy_hits = by_type.get("immobilization_strategy", [])
    condition_hits = by_type.get("formulation_condition", [])
    performance_hits = by_type.get("performance_metric", []) + by_type.get("table_comparison_row", [])

    evidence_lines: List[str] = []
    evidence_lines.extend(strategy_lines(strategy_hits, retrieval))
    evidence_lines.extend(condition_lines(condition_hits, retrieval))
    evidence_lines.extend(section_lines(performance_hits, retrieval, fallback=""))
    if not evidence_lines:
        evidence_lines.append("- 当前检索结果没有可直接写入流程结论的可靠 evidence。")

    gap_lines = evidence_gap_lines(strategy_hits, condition_hits, performance_hits)
    gap_lines.extend(condition_conflict_lines(condition_hits, retrieval))
    if review:
        gap_lines.append("- 需复核线索：" + "；".join(review_summaries(review[:3], retrieval)) + "。")
    if not gap_lines:
        gap_lines.append("- 当前未见额外冲突；未命中的流程细节仍不能补写。")

    covered = []
    if strategy_hits:
        covered.append("固定化方式/载体")
    if condition_hits:
        covered.append("固定化条件")
    if performance_hits:
        covered.append("性能验证")
    if covered:
        conclusion = f"{label}。基于当前可用 evidence，可以确认论文中命中了{'、'.join(covered)}相关信息；缺失环节仍按证据不足处理。"
    else:
        conclusion = f"{label}。当前没有命中可直接用于流程结论的可靠 evidence，不能还原完整固定化剂优化流程。"
    lines = [
        "**结论**",
        conclusion,
        "",
        "**论文内证据**",
        *evidence_lines,
        "",
        "**证据缺口/冲突**",
        *gap_lines,
    ]
    return "\n".join(lines)


def select_answer_hits(question: str, retrieval: RetrievalResponse, limit: int) -> List[RetrievalHit]:
    if not retrieval.hits:
        return []
    wanted_numbers = set(re.findall(r"\d+(?:\.\d+)?", question or ""))
    scored = []
    for index, hit in enumerate(retrieval.hits):
        score = float(hit.score or 0.0)
        text = hit_search_text(hit)
        if hit.record_type == "formulation_condition":
            score += 0.30
        elif hit.record_type == "table_comparison_row":
            score += 0.20
        elif hit.record_type == "performance_metric":
            score += 0.16
        elif hit.record_type == "immobilization_strategy":
            score += 0.14
        if wanted_numbers & set(re.findall(r"\d+(?:\.\d+)?", text)):
            score += 0.20
        if not is_primary_fact_hit(hit):
            score -= 0.50
        scored.append((score, index, hit))
    selected = [hit for _, _, hit in sorted(scored, key=lambda item: (-item[0], item[1]))[:limit]]
    return selected


def facts_from_hits(hits: List[RetrievalHit], retrieval: Optional[RetrievalResponse] = None) -> List[Dict[str, str]]:
    facts: List[Dict[str, str]] = []
    for hit in hits:
        ref = reference_index(hit, retrieval)
        if hit.record_type == "formulation_condition":
            facts.extend(condition_facts(hit, ref))
            continue
        if hit.record_type == "table_comparison_row":
            facts.extend(metric_facts(hit, ref))
            continue
        if hit.record_type == "performance_metric":
            facts.extend(metric_facts(hit, ref))
            if facts and facts[-1]["ref"] == ref:
                continue
        if hit.record_type == "immobilization_strategy":
            carrier = hit.extracted.get("carrier") or hit.extracted.get("carrier_variant")
            method = hit.extracted.get("immobilization_method")
            if carrier or method:
                facts.append({"text": f"固定化策略为 {method or '未明方法'}，载体/材料为 {carrier or '未明载体'}", "ref": ref})
                continue
        facts.append({"text": hit_summary(hit), "ref": ref})
    return facts


def condition_facts(hit: RetrievalHit, ref: str) -> List[Dict[str, str]]:
    facts = []
    condition_values = [f"{label} {display_value(value)}" for _, label, value in condition_value_pairs(hit)]
    if condition_values:
        facts.append({"text": "固定化条件包括 " + "、".join(condition_values), "ref": ref})
    else:
        facts.append({"text": hit_summary(hit), "ref": ref})
    return facts


def metric_facts(hit: RetrievalHit, ref: str) -> List[Dict[str, str]]:
    facts = []
    for metric in hit.metrics[:3]:
        name = humanize_key(str(metric.get("name") or "metric"))
        value = metric.get("value")
        unit = metric.get("unit") or ""
        if value not in (None, "", []):
            facts.append({"text": f"性能指标命中 {name} {join_value_unit(value, unit)}", "ref": ref})
    if not facts:
        text = hit_summary(hit)
        facts.append({"text": text, "ref": ref})
    return facts


def section_lines(hits: List[RetrievalHit], retrieval: RetrievalResponse, fallback: str) -> List[str]:
    if not hits:
        return [f"- {fallback}。"] if fallback else []
    lines = []
    seen = set()
    for hit in hits[:3]:
        line = f"- {hit_summary(hit)} [{reference_index(hit, retrieval)}]"
        if line in seen:
            continue
        seen.add(line)
        lines.append(line)
    return lines


def condition_lines(hits: List[RetrievalHit], retrieval: RetrievalResponse) -> List[str]:
    if not hits:
        return []
    lines = []
    seen = set()
    for hit in hits[:3]:
        for fact in condition_facts(hit, reference_index(hit, retrieval)):
            key = fact["text"].lower()
            if key in seen:
                continue
            seen.add(key)
            lines.append(f"- {fact['text']} [{fact['ref']}]")
    return lines


def hit_summary(hit: RetrievalHit) -> str:
    extracted_bits = humanized_extracted_bits(hit)
    if extracted_bits:
        return "；".join(extracted_bits)
    metric_bits = []
    for metric in hit.metrics[:3]:
        name = humanize_key(str(metric.get("name") or "metric"))
        value = metric.get("value")
        unit = metric.get("unit") or ""
        if value not in (None, "", []):
            metric_bits.append(f"{name} {join_value_unit(value, unit)}")
    if metric_bits:
        return "性能指标命中 " + "；".join(metric_bits)
    return re.sub(r"\s+", " ", (hit.source_chunk_text or hit.text or "").strip())[:220]


FIELD_LABELS = {
    "immobilization_method": "固定化方式",
    "carrier": "载体/材料",
    "carrier_variant": "载体/材料",
    "material_class": "材料类型",
    "enzyme_name": "酶",
    "enzyme_loading": "enzyme loading",
    "carrier_amount": "carrier amount",
    "enzyme_to_carrier_ratio": "enzyme/carrier ratio",
    "adsorption_time": "adsorption time",
    "immobilization_time": "固定化时间",
    "pH": "pH",
    "ph": "pH",
    "immobilization_temperature": "固定化温度",
    "temperature": "温度",
    "reuse_cycles": "reuse cycles",
    "residual_activity": "residual activity",
    "activity_recovery": "activity recovery",
    "immobilization_yield": "immobilization yield",
    "biodiesel_yield": "biodiesel yield",
    "yield": "yield",
}

CONDITION_FIELDS = [
    "enzyme_loading",
    "carrier_amount",
    "enzyme_to_carrier_ratio",
    "adsorption_time",
    "immobilization_time",
    "pH",
    "ph",
    "immobilization_temperature",
    "temperature",
]

CONDITION_GROUPS = {
    "enzyme_loading": "enzyme loading",
    "carrier_amount": "carrier amount",
    "enzyme_to_carrier_ratio": "enzyme/carrier ratio",
    "adsorption_time": "固定化时间",
    "immobilization_time": "固定化时间",
    "pH": "pH",
    "ph": "pH",
    "immobilization_temperature": "温度",
    "temperature": "温度",
}


def strategy_lines(hits: List[RetrievalHit], retrieval: RetrievalResponse) -> List[str]:
    grouped: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for hit in hits:
        method = display_value(hit.extracted.get("immobilization_method")).strip()
        carrier = display_value(hit.extracted.get("carrier") or hit.extracted.get("carrier_variant")).strip()
        if not method and not carrier:
            summary = hit_summary(hit)
            key = (summary.lower(), "")
            grouped.setdefault(key, {"text": summary, "refs": []})["refs"].append(reference_index(hit, retrieval))
            continue
        key = (method.lower(), carrier.lower())
        if method and carrier:
            text = f"固定化方式为 {method}，载体/材料为 {carrier}"
        elif method:
            text = f"固定化方式为 {method}"
        else:
            text = f"载体/材料为 {carrier}"
        grouped.setdefault(key, {"text": text, "refs": []})["refs"].append(reference_index(hit, retrieval))
    lines = []
    for item in grouped.values():
        refs = format_refs(item["refs"])
        if len(item["refs"]) > 1:
            lines.append(f"- 多条证据均指向{item['text']} {refs}")
        else:
            lines.append(f"- {item['text']} {refs}")
    return lines


def evidence_gap_lines(
    strategy_hits: List[RetrievalHit],
    condition_hits: List[RetrievalHit],
    performance_hits: List[RetrievalHit],
) -> List[str]:
    lines = []
    if not strategy_hits:
        lines.append("- 固定化剂/载体筛选：当前证据不足。")
    if not condition_hits:
        lines.append("- 固定化条件或优化变量：当前证据不足。")
    if not performance_hits:
        lines.append("- 性能验证：当前证据不足。")
    return lines


def condition_conflict_lines(hits: List[RetrievalHit], retrieval: RetrievalResponse) -> List[str]:
    grouped: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for hit in hits:
        ref = reference_index(hit, retrieval)
        for raw_key, _, value in condition_value_pairs(hit):
            group = CONDITION_GROUPS.get(raw_key, humanize_key(raw_key))
            display = display_value(value)
            normalized = normalize_fact_value(value)
            item = grouped.setdefault(group, {}).setdefault(normalized, {"display": display, "refs": []})
            item["refs"].append(ref)
    lines = []
    for group, values in grouped.items():
        if len(values) <= 1:
            continue
        value_text = "、".join(f"{item['display']} {format_refs(item['refs'])}" for item in values.values())
        lines.append(
            f"- {group} 同时命中 {value_text}，需回看原文确认其对应 immobilization conditions、assay conditions、reaction/application conditions 还是 stability/reuse conditions。"
        )
    return lines


def review_summaries(hits: List[RetrievalHit], retrieval: RetrievalResponse) -> List[str]:
    return [f"{hit_summary(hit)} [{reference_index(hit, retrieval)}]" for hit in hits]


def condition_value_pairs(hit: RetrievalHit) -> List[Tuple[str, str, Any]]:
    extracted = hit.extracted or {}
    pairs = []
    for key in CONDITION_FIELDS:
        value = extracted.get(key)
        if value in (None, "", []):
            continue
        pairs.append((key, humanize_key(key), value))
    return pairs


def humanized_extracted_bits(hit: RetrievalHit) -> List[str]:
    bits = []
    for key, value in (hit.extracted or {}).items():
        if value in (None, "", []) or key in {"table_id", "source_table_id"}:
            continue
        bits.append(f"{humanize_key(str(key))} {display_value(value)}")
        if len(bits) >= 5:
            break
    return bits


def reference_index(hit: RetrievalHit, retrieval: Optional[RetrievalResponse] = None) -> str:
    if retrieval is not None:
        for index, candidate in enumerate(retrieval.hits, start=1):
            if candidate.source_id == hit.source_id:
                return str(index)
    return str(getattr(hit, "_reference_index", "") or 1)


def is_primary_fact_hit(hit: RetrievalHit) -> bool:
    flags = set(hit.quality_flags or []) | set(hit.qa_flags or [])
    return hit.usable_for_ranking and not hit.requires_review and hit.qa_status != "fail" and not flags


def asks_condition_type(question: str) -> bool:
    text = question or ""
    return bool(re.search(r"assay|反应条件|固定化条件|区分|condition", text, re.I))


def paper_label(hits: List[RetrievalHit]) -> str:
    for hit in hits:
        if hit.document_id or hit.source_pdf:
            return " / ".join(part for part in [hit.document_id, hit.source_pdf] if part)
    return "目标论文已限定，但缺少文献编号"


def value_label(value: Any) -> str:
    return display_value(value)


def humanize_key(key: str) -> str:
    return FIELD_LABELS.get(key, key.replace("_", " "))


def display_value(value: Any) -> str:
    if value in (None, "", []):
        return ""
    if isinstance(value, dict):
        if "value" in value:
            base = display_value(value.get("value"))
            unit = str(value.get("unit") or "").strip()
            return " ".join(part for part in [base, unit] if part)
        parts = []
        for key, item in value.items():
            if item in (None, "", []):
                continue
            parts.append(f"{humanize_key(str(key))} {display_value(item)}")
            if len(parts) >= 4:
                break
        return "；".join(parts)
    if isinstance(value, list):
        return "、".join(display_value(item) for item in value if item not in (None, "", []))
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def join_value_unit(value: Any, unit: Any) -> str:
    base = display_value(value)
    unit_text = str(unit or "").strip()
    if not unit_text:
        return base
    return f"{base} {unit_text}"


def normalize_fact_value(value: Any) -> str:
    return re.sub(r"\s+", " ", display_value(value).strip().lower())


def format_refs(refs: List[str]) -> str:
    deduped = []
    for ref in refs:
        if ref not in deduped:
            deduped.append(ref)
    return "、".join(f"[{ref}]" for ref in deduped)


def hit_search_text(hit: RetrievalHit) -> str:
    return "\n".join(
        [
            hit.text or "",
            hit.source_chunk_text or "",
            json.dumps(hit.extracted, ensure_ascii=False, sort_keys=True),
            json.dumps(hit.metrics, ensure_ascii=False, sort_keys=True),
        ]
    )
