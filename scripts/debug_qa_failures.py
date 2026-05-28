from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a bucketed debug table for failed layered QA benchmark cases.")
    parser.add_argument("--qa-report", required=True, type=Path, help="JSON output from scripts/benchmark_qa_system.py")
    parser.add_argument(
        "--benchmark",
        action="append",
        default=[],
        type=Path,
        help="Benchmark manifest path. Repeat to include all manifests used by the QA report.",
    )
    parser.add_argument("--csv", required=True, type=Path, help="Output CSV path.")
    parser.add_argument("--markdown", required=True, type=Path, help="Output Markdown summary path.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = json.loads(args.qa_report.read_text(encoding="utf-8"))
    manifests = [load_manifest(path) for path in args.benchmark]
    case_index = index_cases(manifests)
    failed_rows = []
    for result in report.get("results") or []:
        if result.get("ok"):
            continue
        case = case_index.get(str(result.get("id")), {})
        failed_rows.append(build_debug_row(result, case))

    args.csv.parent.mkdir(parents=True, exist_ok=True)
    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    write_csv(args.csv, failed_rows)
    args.markdown.write_text(render_markdown(report, failed_rows), encoding="utf-8")
    print(
        json.dumps(
            {
                "failed": len(failed_rows),
                "by_bucket": dict(Counter(row["bucket"] for row in failed_rows)),
                "csv": str(args.csv),
                "markdown": str(args.markdown),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def load_manifest(path: Path) -> Dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["_path"] = str(path)
    return payload


def index_cases(manifests: Sequence[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    cases: Dict[str, Dict[str, Any]] = {}
    for manifest in manifests:
        defaults = manifest.get("defaults") or {}
        benchmark_name = manifest.get("name") or Path(str(manifest.get("_path", ""))).stem
        for raw_case in manifest.get("cases") or []:
            case = dict(defaults)
            case.update(raw_case)
            case["benchmark"] = benchmark_name
            if case.get("id"):
                cases[str(case["id"])] = case
    return cases


def build_debug_row(result: Dict[str, Any], case: Dict[str, Any]) -> Dict[str, Any]:
    actual = result.get("actual") or {}
    checks = result.get("checks") or {}
    hits = list(actual.get("hits") or [])
    expected = list(case.get("expected_evidence") or [])
    failed_checks = failed_check_names(checks)
    bucket = classify_bucket(result, case, hits, failed_checks)
    query_plan = actual.get("query_plan") or {}
    expected_docs = sorted({str(item.get("document_id")) for item in expected if item.get("document_id")})
    expected_sources = sorted({str(item.get("source_id")) for item in expected if item.get("source_id")})
    expected_record_types = sorted({str(item.get("record_type")) for item in expected if item.get("record_type")})
    top_docs = sorted({str(hit.get("document_id")) for hit in hits if hit.get("document_id")})
    top_sources = sorted({str(hit.get("source_id")) for hit in hits if hit.get("source_id")})
    top_record_types = sorted({str(hit.get("record_type")) for hit in hits if hit.get("record_type")})
    return {
        "benchmark": result.get("benchmark") or case.get("benchmark") or "",
        "case_id": result.get("id") or "",
        "kind": result.get("kind") or case.get("kind") or "",
        "endpoint": result.get("endpoint") or case.get("endpoint") or "",
        "difficulty": result.get("difficulty") or case.get("difficulty") or "",
        "bucket": bucket,
        "query": result.get("query") or case.get("query") or "",
        "expected_evidence": compact_json(expected),
        "expected_answer_facts": compact_json(case.get("expected_answer_facts") or []),
        "failed_checks": ", ".join(failed_checks),
        "evidence_ok": checks.get("evidence_ok"),
        "plan_ok": checks.get("plan_ok"),
        "facts_ok": checks.get("facts_ok"),
        "citation_ok": checks.get("citation_ok"),
        "formulation_ok": checks.get("formulation_ok"),
        "expected_evidence_ranks": compact_json(checks.get("expected_evidence_ranks") or []),
        "query_plan_intents": compact_json(query_plan.get("intents") or []),
        "query_plan_record_type_priorities": compact_json(query_plan.get("record_type_priorities") or []),
        "query_plan_point_type_priorities": compact_json(query_plan.get("point_type_priorities") or []),
        "query_plan_document_id": query_plan.get("document_id") or "",
        "query_plan_source_pdf": query_plan.get("source_pdf") or "",
        "expected_docs": compact_json(expected_docs),
        "top_docs": compact_json(top_docs),
        "expected_document_in_top8": bool(set(expected_docs) & set(top_docs)) if expected_docs else "",
        "expected_sources": compact_json(expected_sources),
        "top_sources": compact_json(top_sources),
        "expected_source_in_top8": bool(set(expected_sources) & set(top_sources)) if expected_sources else "",
        "expected_record_types": compact_json(expected_record_types),
        "top_record_types": compact_json(top_record_types),
        "expected_record_type_in_top8": bool(set(expected_record_types) & set(top_record_types))
        if expected_record_types
        else "",
        "top_hits": compact_json([compact_hit(hit) for hit in hits[:8]]),
    }


def classify_bucket(
    result: Dict[str, Any],
    case: Dict[str, Any],
    hits: Sequence[Dict[str, Any]],
    failed_checks: Sequence[str],
) -> str:
    checks = result.get("checks") or {}
    expected = list(case.get("expected_evidence") or [])
    expected_docs = {str(item.get("document_id")) for item in expected if item.get("document_id")}
    expected_sources = {str(item.get("source_id")) for item in expected if item.get("source_id")}
    expected_record_types = {str(item.get("record_type")) for item in expected if item.get("record_type")}
    hit_docs = {str(hit.get("document_id")) for hit in hits if hit.get("document_id")}
    hit_sources = {str(hit.get("source_id")) for hit in hits if hit.get("source_id")}
    hit_record_types = {str(hit.get("record_type")) for hit in hits if hit.get("record_type")}

    if (result.get("actual") or {}).get("error"):
        return "runtime_error"
    if "plan_ok" in failed_checks and not expected_docs:
        return "plan_mismatch"
    if expected_docs and not (expected_docs & hit_docs):
        return "document_missing"
    if expected_sources and not (expected_sources & hit_sources):
        if "plan_ok" in failed_checks:
            return "plan_mismatch"
        if expected_record_types and not (expected_record_types & hit_record_types):
            return "record_type_mismatch"
        return "document_hit_source_missing"
    if expected_record_types and not (expected_record_types & hit_record_types):
        return "record_type_mismatch"
    if "plan_ok" in failed_checks:
        return "plan_mismatch"
    if "citation_ok" in failed_checks:
        return "citation_mismatch"
    if checks.get("evidence_ok") and (
        "facts_ok" in failed_checks or "formulation_ok" in failed_checks or "condition_type_ok" in failed_checks
    ):
        return "response_selection_mismatch"
    if any(hit.get("requires_review") or hit.get("qa_status") == "fail" for hit in hits[:5]):
        return "bad_gold_or_requires_review"
    return "evidence_mismatch"


def failed_check_names(checks: Dict[str, Any]) -> List[str]:
    names = []
    for key, value in checks.items():
        if key.endswith("_ok") and value is False:
            names.append(key)
    return names


def compact_hit(hit: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "rank": hit.get("rank"),
        "document_id": hit.get("document_id"),
        "source_id": hit.get("source_id"),
        "record_type": hit.get("record_type"),
        "point_type": hit.get("point_type"),
        "score": round_float(hit.get("score")),
        "rerank_score": round_float(hit.get("rerank_score")),
        "lexical_score": round_float(hit.get("lexical_score")),
        "route_labels": hit.get("route_labels") or [],
        "citation": hit.get("citation"),
        "usable_for_ranking": hit.get("usable_for_ranking"),
        "requires_review": hit.get("requires_review"),
        "qa_flags": hit.get("qa_flags") or [],
        "quality_flags": hit.get("quality_flags") or [],
    }


def write_csv(path: Path, rows: Sequence[Dict[str, Any]]) -> None:
    fieldnames = [
        "benchmark",
        "case_id",
        "kind",
        "endpoint",
        "difficulty",
        "bucket",
        "query",
        "expected_evidence",
        "expected_answer_facts",
        "failed_checks",
        "evidence_ok",
        "plan_ok",
        "facts_ok",
        "citation_ok",
        "formulation_ok",
        "expected_evidence_ranks",
        "query_plan_intents",
        "query_plan_record_type_priorities",
        "query_plan_point_type_priorities",
        "query_plan_document_id",
        "query_plan_source_pdf",
        "expected_docs",
        "top_docs",
        "expected_document_in_top8",
        "expected_sources",
        "top_sources",
        "expected_source_in_top8",
        "expected_record_types",
        "top_record_types",
        "expected_record_type_in_top8",
        "top_hits",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def render_markdown(report: Dict[str, Any], rows: Sequence[Dict[str, Any]]) -> str:
    by_bucket = Counter(row["bucket"] for row in rows)
    by_benchmark = Counter(row["benchmark"] for row in rows)
    by_endpoint = Counter(row["endpoint"] for row in rows)
    by_doc: Counter[str] = Counter()
    for row in rows:
        docs = json.loads(row["expected_docs"]) if row.get("expected_docs") else []
        for doc in docs:
            by_doc[doc] += 1
    lines = [
        "# QA Failure Debug",
        "",
        f"- Total: {report.get('passed')}/{report.get('total')} passed",
        f"- Failed: {len(rows)}",
        f"- Pass rate: {float(report.get('pass_rate') or 0.0):.3f}",
        "",
        "## By Bucket",
        "",
        "| Bucket | Count |",
        "| --- | ---: |",
    ]
    lines.extend(f"| {bucket} | {count} |" for bucket, count in by_bucket.most_common())
    lines.extend(["", "## By Benchmark", "", "| Benchmark | Count |", "| --- | ---: |"])
    lines.extend(f"| {name} | {count} |" for name, count in by_benchmark.most_common())
    lines.extend(["", "## By Endpoint", "", "| Endpoint | Count |", "| --- | ---: |"])
    lines.extend(f"| {name} | {count} |" for name, count in by_endpoint.most_common())
    lines.extend(["", "## By Expected Document", "", "| Document | Count |", "| --- | ---: |"])
    lines.extend(f"| {name} | {count} |" for name, count in by_doc.most_common(20))
    lines.extend(["", "## Failed Cases", "", "| Case | Endpoint | Bucket | Failed checks | Expected doc in Top-8 | Expected source in Top-8 |", "| --- | --- | --- | --- | --- | --- |"])
    for row in rows:
        lines.append(
            "| {case_id} | {endpoint} | {bucket} | {checks} | {doc_hit} | {source_hit} |".format(
                case_id=row["case_id"],
                endpoint=row["endpoint"],
                bucket=row["bucket"],
                checks=row["failed_checks"],
                doc_hit=row["expected_document_in_top8"],
                source_hit=row["expected_source_in_top8"],
            )
        )
    lines.append("")
    return "\n".join(lines)


def round_float(value: Any) -> Any:
    if isinstance(value, (int, float)):
        return round(float(value), 6)
    return value


def compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


if __name__ == "__main__":
    main()
