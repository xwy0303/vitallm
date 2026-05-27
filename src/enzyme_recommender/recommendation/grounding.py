from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

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
    selected = select_answer_hits(question, retrieval, limit=7)
    usable = [hit for hit in selected if is_primary_fact_hit(hit)]
    review = [hit for hit in selected if not is_primary_fact_hit(hit)]
    by_type: Dict[str, List[RetrievalHit]] = {}
    for hit in usable:
        by_type.setdefault(hit.record_type or hit.point_type, []).append(hit)
    label = paper_label(selected)
    lines = [
        "1. 论文定位",
        f"- {label}。",
        "2. 研究目标",
        f"- 该问题需要从单篇论文内还原固定化剂/载体筛选、固定化条件和性能验证；当前答案只基于检索到的 evidence。",
        "3. 固定化剂/载体筛选",
    ]
    lines.extend(section_lines(by_type.get("immobilization_strategy", []), retrieval, fallback="不足"))
    lines.append("4. 优化变量")
    lines.extend(section_lines(by_type.get("formulation_condition", []), retrieval, fallback="不足"))
    lines.append("5. 最优条件")
    lines.extend(condition_lines(by_type.get("formulation_condition", []), retrieval))
    lines.append("6. 性能验证")
    lines.extend(section_lines(by_type.get("performance_metric", []) + by_type.get("table_comparison_row", []), retrieval, fallback="不足"))
    lines.append("7. 证据缺口与需复核项")
    if review:
        for hit in review[:3]:
            lines.append(f"- {hit_summary(hit)} [{reference_index(hit, retrieval)}] 存在 review/QA 风险，只能作为复核线索。")
    else:
        lines.append("- 未命中的流程环节应视为证据不足，不能补写。")
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
    extracted = hit.extracted or {}
    facts = []
    condition_values = []
    for key in [
        "enzyme_loading",
        "carrier_amount",
        "enzyme_to_carrier_ratio",
        "adsorption_time",
        "immobilization_time",
        "pH",
        "ph",
        "immobilization_temperature",
        "temperature",
    ]:
        value = extracted.get(key)
        if value not in (None, "", []):
            condition_values.append(f"{key}={value_label(value)}")
    if condition_values:
        facts.append({"text": "固定化条件包括 " + "；".join(condition_values), "ref": ref})
    else:
        facts.append({"text": hit_summary(hit), "ref": ref})
    return facts


def metric_facts(hit: RetrievalHit, ref: str) -> List[Dict[str, str]]:
    facts = []
    for metric in hit.metrics[:3]:
        name = metric.get("name") or "metric"
        value = metric.get("value")
        unit = metric.get("unit") or ""
        if value not in (None, "", []):
            facts.append({"text": f"{name}: {value}{unit}", "ref": ref})
    if not facts:
        text = hit_summary(hit)
        facts.append({"text": text, "ref": ref})
    return facts


def section_lines(hits: List[RetrievalHit], retrieval: RetrievalResponse, fallback: str) -> List[str]:
    if not hits:
        return [f"- {fallback}。"]
    lines = []
    for hit in hits[:3]:
        lines.append(f"- {hit_summary(hit)} [{reference_index(hit, retrieval)}]")
    return lines


def condition_lines(hits: List[RetrievalHit], retrieval: RetrievalResponse) -> List[str]:
    if not hits:
        return ["- 不足。"]
    lines = []
    for hit in hits[:3]:
        for fact in condition_facts(hit, reference_index(hit, retrieval)):
            lines.append(f"- {fact['text']} [{fact['ref']}]")
    return lines


def hit_summary(hit: RetrievalHit) -> str:
    extracted_bits = []
    for key, value in (hit.extracted or {}).items():
        if value in (None, "", []):
            continue
        if key in {"table_id", "source_table_id"}:
            continue
        extracted_bits.append(f"{key}={value_label(value)}")
        if len(extracted_bits) >= 5:
            break
    if extracted_bits:
        return "；".join(extracted_bits)
    metric_bits = []
    for metric in hit.metrics[:3]:
        name = metric.get("name")
        value = metric.get("value")
        unit = metric.get("unit") or ""
        if name and value not in (None, "", []):
            metric_bits.append(f"{name}={value}{unit}")
    if metric_bits:
        return "；".join(metric_bits)
    return re.sub(r"\s+", " ", (hit.source_chunk_text or hit.text or "").strip())[:220]


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
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def hit_search_text(hit: RetrievalHit) -> str:
    return "\n".join(
        [
            hit.text or "",
            hit.source_chunk_text or "",
            json.dumps(hit.extracted, ensure_ascii=False, sort_keys=True),
            json.dumps(hit.metrics, ensure_ascii=False, sort_keys=True),
        ]
    )
