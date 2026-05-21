from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


PERCENT_RE = re.compile(r"(?P<value>\d+(?:\.\d+)?)\s*%")
PH_RE = re.compile(r"\bpH(?:\s+value)?\s*(?:was|of|=|at|to)?\s*(?P<value>\d+(?:\.\d+)?)", re.I)
LOADING_RE = re.compile(r"\b(?:BCL[-\s\w]*?)?loading(?:\s+of)?\s*(?P<value>\d+(?:\.\d+)?)\s*mg\b", re.I)
ADSORPTION_TIME_RE = re.compile(r"\badsorption time\s*(?P<value>\d+(?:\.\d+)?)\s*min\b", re.I)
TEMPERATURE_RE = re.compile(r"\b(?P<value>\d+(?:\.\d+)?)\s*(?:°C|\^\s*\{\s*\\circ\s*\}\s*C|C)\b")
BIODIESEL_YIELD_RE = re.compile(r"\bbiodiesel(?:\s+\w+){0,4}?\s+(?:with|of|was|reached)?\s*(?P<value>\d+(?:\.\d+)?)\s*%\s+yield\b", re.I)
REUSE_RE = re.compile(r"\b(?:reused|reuse|reusability).*?(?P<cycles>\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s+cycles?\b", re.I)
ACTIVITY_RECOVERY_RE = re.compile(r"\bactivity recovery(?:\s+\w+){0,8}?\s*(?:up to|of|was|reached|value of)?\s*(?P<value>\d+(?:\.\d+)?)\s*%", re.I)

WORD_NUMBERS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}


def extract_evidence_records(input_dir: Path) -> Dict[str, Any]:
    manifest = load_json(input_dir / "document_manifest.json")
    candidates = load_jsonl(input_dir / "extraction_candidates.jsonl")
    tables = load_jsonl(input_dir / "table_records.jsonl")

    records: List[Dict[str, Any]] = []
    for candidate in candidates:
        if candidate.get("candidate_source") != "rag_chunk":
            continue
        records.extend(extract_from_text_candidate(candidate))

    for table in tables:
        records.extend(extract_from_table_record(table))

    records = deduplicate_records(records)
    review_queue = [record for record in records if record["requires_review"]]
    report = build_validation_report(manifest, candidates, tables, records, review_queue)
    return {
        "evidence_records": records,
        "review_queue": review_queue,
        "validation_report": report,
    }


def extract_from_text_candidate(candidate: Dict[str, Any]) -> List[Dict[str, Any]]:
    text = candidate.get("text") or ""
    normalized = normalize_scientific_text(text)
    records: List[Dict[str, Any]] = []

    enzyme_fields = extract_enzyme_identity(normalized)
    if enzyme_fields:
        records.append(make_record(candidate, "enzyme_identity", enzyme_fields, [], evidence_span=select_span(text, "lipase")))

    strategy_fields = extract_immobilization_strategy(normalized)
    if strategy_fields:
        records.append(
            make_record(candidate, "immobilization_strategy", strategy_fields, [], evidence_span=select_span(text, "ZIF-8"))
        )

    condition_fields = extract_formulation_conditions(normalized)
    if condition_fields:
        records.append(
            make_record(
                candidate,
                "formulation_condition",
                condition_fields,
                [],
                evidence_span=select_span(text, "optimal conditions") or select_span(text, "loading"),
            )
        )

    metrics = extract_performance_metrics(normalized)
    if metrics:
        records.append(
            make_record(
                candidate,
                "performance_metric",
                {},
                metrics,
                evidence_span=select_span(text, "activity recovery")
                or select_span(text, "biodiesel")
                or text[:500],
            )
        )

    return records


def extract_from_table_record(table: Dict[str, Any]) -> List[Dict[str, Any]]:
    records = []
    columns = table.get("columns") or []
    rows = table.get("rows") or []
    for row_index, row in enumerate(rows, start=1):
        row_map = row_to_map(columns, row)
        text = table_row_text(row_map)
        extracted = {
            "enzyme_name": row_map.get("Enzyme"),
            "substrate": row_map.get("Substrate"),
            "operating_conditions": row_map.get("Operating Conditions"),
            "reaction_system": row_map.get("System"),
            "acyl_acceptor": row_map.get("Acyl Acceptor"),
            "reference": row_map.get("References"),
            "table_id": table.get("table_id"),
            "row_index": row_index,
        }
        metrics = []
        yield_value = parse_float(row_map.get("Yield (%)"))
        if yield_value is not None:
            metrics.append(
                {
                    "name": "biodiesel_yield",
                    "value": yield_value,
                    "unit": "%",
                    "raw": row_map.get("Yield (%)"),
                }
            )
        reuse = parse_reuse(row_map.get("Reusability and Last Yield (%)"))
        if reuse:
            metrics.append(reuse)

        row_source = dict(table)
        row_source["quality_flags"] = []
        records.append(
            make_record(
                row_source,
                "table_comparison_row",
                extracted,
                metrics,
                evidence_span=text,
                source_kind="table_record",
                extra_quality_flags=table_row_quality_flags(row_map),
            )
        )
    return records


def extract_enzyme_identity(text: str) -> Dict[str, Any]:
    fields: Dict[str, Any] = {}
    if re.search(r"Burkholderia\s+cepacia\s+lipase", text, re.I):
        fields["enzyme_name"] = "Burkholderia cepacia lipase"
        fields["enzyme_abbreviation"] = "BCL" if re.search(r"\bBCL\b", text) else None
        fields["ec_number"] = "3.1.1.3" if re.search(r"E\.?C\.?\s*3\.1\.1\.3", text, re.I) else None
    elif re.search(r"\bBCL\b", text):
        fields["enzyme_name"] = "Burkholderia cepacia lipase"
        fields["enzyme_abbreviation"] = "BCL"
    elif re.search(r"\blipase\b", text, re.I):
        fields["enzyme_name"] = "lipase"
    return {key: value for key, value in fields.items() if value is not None}


def extract_immobilization_strategy(text: str) -> Dict[str, Any]:
    fields: Dict[str, Any] = {}
    if re.search(r"\bZIF-8\b", text, re.I):
        fields["carrier"] = "ZIF-8"
        if re.search(r"hierarchical\s+ZIF-8|hierarchical\s+mesoporous", text, re.I):
            fields["carrier_variant"] = "hierarchical mesoporous ZIF-8"
        fields["material_class"] = "MOF"
    if re.search(r"\badsorption\b", text, re.I):
        fields["immobilization_method"] = "adsorption"
    if re.search(r"\bBCL-ZIF-8\b", text):
        fields["immobilized_product"] = "BCL-ZIF-8"
    return fields


def extract_formulation_conditions(text: str) -> Dict[str, Any]:
    conditions: Dict[str, Any] = {}
    loading = last_match_float(LOADING_RE, text)
    if loading is not None:
        conditions["enzyme_loading"] = {"value": loading, "unit": "mg"}
    adsorption_time = first_match_float(ADSORPTION_TIME_RE, text)
    if adsorption_time is not None:
        conditions["adsorption_time"] = {"value": adsorption_time, "unit": "min"}
    ph = last_match_float(PH_RE, text)
    if ph is not None:
        conditions["pH"] = ph
    temperatures = [float(match.group("value")) for match in TEMPERATURE_RE.finditer(text)]
    selected_temp = select_temperature(temperatures)
    if selected_temp is not None:
        conditions["immobilization_temperature"] = {"value": selected_temp, "unit": "degC"}
    return conditions


def extract_performance_metrics(text: str) -> List[Dict[str, Any]]:
    metrics: List[Dict[str, Any]] = []
    for match in ACTIVITY_RECOVERY_RE.finditer(text):
        metrics.append(
            {
                "name": "activity_recovery",
                "value": float(match.group("value")),
                "unit": "%",
                "raw": match.group(0),
            }
        )
    biodiesel_yield = first_match_float(BIODIESEL_YIELD_RE, text)
    if biodiesel_yield is not None:
        metrics.append(
            {
                "name": "biodiesel_yield",
                "value": biodiesel_yield,
                "unit": "%",
                "raw": f"{biodiesel_yield}%",
            }
        )
    reuse_match = REUSE_RE.search(text)
    if reuse_match:
        cycles = parse_cycle_count(reuse_match.group("cycles"))
        if cycles is not None:
            metrics.append(
                {
                    "name": "reuse_cycles",
                    "value": cycles,
                    "unit": "cycle",
                    "raw": reuse_match.group(0),
                }
            )
    return deduplicate_metrics(metrics)


def make_record(
    source: Dict[str, Any],
    record_type: str,
    extracted: Dict[str, Any],
    metrics: Sequence[Dict[str, Any]],
    evidence_span: str,
    source_kind: str = "rag_chunk",
    extra_quality_flags: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    quality_flags = sorted(set(source.get("quality_flags") or []) | set(extra_quality_flags or []))
    review_reasons = infer_review_reasons(quality_flags, metrics, extracted)
    record = {
        "evidence_id": "",
        "record_type": record_type,
        "candidate_source": source_kind,
        "document_id": source.get("document_id"),
        "source_pdf": source.get("source_pdf"),
        "source_id": source.get("source_id") or source.get("table_id") or source.get("chunk_id"),
        "source_block_indices": source.get("source_block_indices")
        or ([source["source_block_index"]] if source.get("source_block_index") is not None else []),
        "page_start": source.get("page_start", source.get("page_idx")),
        "page_end": source.get("page_end", source.get("page_idx")),
        "bbox": source.get("bbox"),
        "section": source.get("section"),
        "evidence_span": normalize_space(evidence_span)[:1500],
        "extracted": extracted,
        "metrics": list(metrics),
        "confidence": confidence_for(record_type, quality_flags),
        "quality_flags": quality_flags,
        "review_reasons": review_reasons,
        "requires_review": bool(review_reasons),
    }
    record["evidence_id"] = make_evidence_id(record)
    return record


def infer_review_reasons(
    quality_flags: Sequence[str],
    metrics: Sequence[Dict[str, Any]],
    extracted: Dict[str, Any],
) -> List[str]:
    reasons = set()
    if quality_flags:
        reasons.add("upstream_quality_flags")
    for metric in metrics:
        value = metric.get("value")
        name = metric.get("name")
        if isinstance(value, (int, float)) and name in {"activity_recovery", "biodiesel_yield"} and value > 100:
            reasons.add("metric_percent_gt_100")
        if metric.get("unit") is None:
            reasons.add("metric_missing_unit")
    if extracted.get("reference") and extracted["reference"] != "This study" and not str(extracted["reference"]).startswith("["):
        reasons.add("malformed_reference")
    return sorted(reasons)


def confidence_for(record_type: str, quality_flags: Sequence[str]) -> str:
    if quality_flags:
        return "low"
    if record_type in {"table_comparison_row", "formulation_condition"}:
        return "medium"
    return "medium"


def build_validation_report(
    manifest: Dict[str, Any],
    candidates: Sequence[Dict[str, Any]],
    tables: Sequence[Dict[str, Any]],
    records: Sequence[Dict[str, Any]],
    review_queue: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    return {
        "document_id": manifest.get("document_id"),
        "source_pdf": manifest.get("source_pdf"),
        "input_counts": {
            "extraction_candidates": len(candidates),
            "table_records": len(tables),
        },
        "output_counts": {
            "evidence_records": len(records),
            "review_queue": len(review_queue),
        },
        "record_type_counts": count_by(records, "record_type"),
        "quality_flag_counts": count_flags(records, "quality_flags"),
        "review_reason_counts": count_flags(records, "review_reasons"),
        "notes": [
            "Rule-based extractor output is a first-pass evidence layer, not final curated facts.",
            "Records with requires_review=true must not be used for ranking until manually or programmatically validated.",
        ],
    }


def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def load_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            payload = json.loads(line)
            if not isinstance(payload, dict):
                raise ValueError(f"expected JSON object at {path}:{line_number}")
            rows.append(payload)
    return rows


def normalize_scientific_text(text: str) -> str:
    text = text.replace("$", " ")
    text = re.sub(r"(\d)\s+(\d)\s*\\?\s*\^\s*\{\s*\\circ\s*\}\s*C", r"\1\2 C", text)
    text = re.sub(r"(\d)\s+(\d)\s*~?\s*\^\s*\{\s*\\circ\s*\}\s*\\mathrm\s*\{\s*C\s*\}", r"\1\2 C", text)
    text = re.sub(r"\s+", " ", text)
    text = text.replace("\\ ^ { \\circ }", "°")
    text = text.replace("^ { \\circ }", "°")
    text = re.sub(r"(?<=\d)\s+(?=\d\s*(?:°|C|mg|min|h|%))", "", text)
    return text


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def select_span(text: str, anchor: str, window: int = 420) -> str:
    if not anchor:
        return normalize_space(text[:window])
    index = text.lower().find(anchor.lower())
    if index < 0:
        return normalize_space(text[:window])
    start = max(index - window // 3, 0)
    end = min(index + window, len(text))
    return normalize_space(text[start:end])


def first_match_float(pattern: re.Pattern[str], text: str) -> Optional[float]:
    match = pattern.search(text)
    if not match:
        return None
    return float(match.group("value"))


def last_match_float(pattern: re.Pattern[str], text: str) -> Optional[float]:
    matches = list(pattern.finditer(text))
    if not matches:
        return None
    return float(matches[-1].group("value"))


def select_temperature(values: Sequence[float]) -> Optional[float]:
    if not values:
        return None
    preferred = [value for value in values if 10 <= value <= 80]
    if not preferred:
        return None
    if 25 in preferred:
        return 25.0
    return preferred[0]


def parse_cycle_count(value: str) -> Optional[int]:
    value = value.lower().strip()
    if value in WORD_NUMBERS:
        return WORD_NUMBERS[value]
    try:
        return int(value)
    except ValueError:
        return None


def parse_float(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    match = re.search(r"\d+(?:\.\d+)?", value)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def parse_reuse(value: Optional[str]) -> Optional[Dict[str, Any]]:
    if not value:
        return None
    match = re.search(r"(?P<cycles>\d+)\s*cycle\s*;\s*(?P<last_yield>\d+(?:\.\d+)?)", value, re.I)
    if not match:
        return None
    return {
        "name": "reusability_last_yield",
        "value": float(match.group("last_yield")),
        "unit": "%",
        "cycle": int(match.group("cycles")),
        "raw": value,
    }


def row_to_map(columns: Sequence[str], row: Sequence[str]) -> Dict[str, str]:
    return {column: row[index] if index < len(row) else "" for index, column in enumerate(columns)}


def table_row_text(row_map: Dict[str, str]) -> str:
    return "; ".join(f"{key}: {value}" for key, value in row_map.items() if value)


def table_row_quality_flags(row_map: Dict[str, str]) -> List[str]:
    flags = []
    yield_value = parse_float(row_map.get("Yield (%)"))
    if yield_value is not None and yield_value > 100:
        flags.append("suspicious_table_yield_gt_100")
    reference = row_map.get("References")
    if reference and reference != "This study" and not reference.startswith("["):
        flags.append("suspicious_reference_cell")
    if not row_map.get("Enzyme"):
        flags.append("missing_enzyme_cell")
    return sorted(set(flags))


def deduplicate_metrics(metrics: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    deduped = []
    for metric in metrics:
        key = (metric.get("name"), metric.get("value"), metric.get("unit"), metric.get("cycle"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(metric)
    return deduped


def deduplicate_records(records: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    deduped = []
    for record in records:
        key = (
            record.get("record_type"),
            record.get("source_id"),
            json.dumps(record.get("extracted"), sort_keys=True, ensure_ascii=False),
            json.dumps(record.get("metrics"), sort_keys=True, ensure_ascii=False),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(record)
    return deduped


def make_evidence_id(record: Dict[str, Any]) -> str:
    payload = {
        "record_type": record.get("record_type"),
        "source_id": record.get("source_id"),
        "extracted": record.get("extracted"),
        "metrics": record.get("metrics"),
        "span": record.get("evidence_span"),
    }
    digest = hashlib.sha1(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    return f"ev_{digest[:16]}"


def count_by(rows: Sequence[Dict[str, Any]], key: str) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for row in rows:
        value = str(row.get(key) or "<missing>")
        counts[value] = counts.get(value, 0) + 1
    return counts


def count_flags(rows: Sequence[Dict[str, Any]], key: str) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for row in rows:
        for flag in row.get(key, []):
            counts[flag] = counts.get(flag, 0) + 1
    return counts
