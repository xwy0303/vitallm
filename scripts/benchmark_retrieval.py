from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence

from enzyme_recommender.rag.retrieval import RetrievalHit
from enzyme_recommender.runtime import RuntimeServices


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run curated retrieval benchmark queries against Qdrant.")
    parser.add_argument("--config", default=Path("configs/local.yaml"), type=Path)
    parser.add_argument("--benchmark", default=Path("benchmarks/retrieval_smoke.json"), type=Path)
    parser.add_argument("--collection", default=None)
    parser.add_argument("--top-k", default=None, type=int)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--allow-failures", action="store_true", help="Report metrics without returning a failing exit code.")
    parser.add_argument("--output", default=None, type=Path, help="Optional JSON path for benchmark audit output.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    runtime = RuntimeServices.from_config_file(args.config)
    if args.collection:
        runtime.config.vector_store.collection = args.collection
    benchmark = load_benchmark(args.benchmark)
    retriever = runtime.retriever()
    results = []
    for item in benchmark["queries"]:
        case_kind = str(item.get("kind") or "positive")
        top_k = args.top_k or int(item.get("top_k") or runtime.config.retrieval.top_k)
        usable_only = bool(item.get("usable_only", runtime.config.retrieval.usable_only))
        point_type = item.get("point_type")
        try:
            response = retriever.retrieve(
                query=item["query"],
                top_k=top_k,
                point_type=point_type,
                usable_only=usable_only,
            )
            score = evaluate_case(response.hits, item)
            expected_plan = item.get("expected_plan") or {}
            plan_score = evaluate_query_plan(response.query_plan, expected_plan)
            result = {
                "id": item["id"],
                "kind": case_kind,
                "query": item["query"],
                "ok": score["ok"],
                "plan_ok": plan_score["ok"],
                "rank": score["rank"],
                "expected_ok": score["expected_ok"],
                "forbidden_ok": score["forbidden_ok"],
                "forbidden_hits": score["forbidden_hits"],
                "top_k": top_k,
                "query_plan": response.query_plan.model_dump(mode="json") if response.query_plan else None,
                "plan_checks": plan_score["checks"],
                "hits": [
                    {
                        "rank": index,
                        "score": hit.score,
                        "document_id": hit.document_id,
                        "source_id": hit.source_id,
                        "source_evidence_id": hit.source_evidence_id,
                        "citation": hit.citation,
                        "point_type": hit.point_type,
                        "record_type": hit.record_type,
                        "candidate_source": hit.candidate_source,
                        "curation_status": hit.curation_status,
                        "route_labels": hit.route_labels,
                        "qa_status": hit.qa_status,
                        "qa_flags": hit.qa_flags,
                        "quality_flags": hit.quality_flags,
                        "review_reasons": hit.review_reasons,
                        "requires_review": hit.requires_review,
                        "usable_for_ranking": hit.usable_for_ranking,
                    }
                    for index, hit in enumerate(response.hits, start=1)
                ],
            }
        except Exception as exc:
            result = {
                "id": item["id"],
                "kind": case_kind,
                "query": item["query"],
                "ok": False,
                "plan_ok": False,
                "rank": None,
                "expected_ok": False,
                "forbidden_ok": False,
                "forbidden_hits": [],
                "top_k": top_k,
                "error": str(exc),
            }
        results.append(result)

    summary = summarize_results(benchmark["name"], retriever.qdrant_config.collection, results)
    if args.output:
        write_summary(args.output, summary)
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return
    print_human_summary(summary)
    if not summary["all_passed"] and not args.allow_failures:
        raise SystemExit(2)


def load_benchmark(path: Path) -> Dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("queries"), list):
        raise ValueError(f"invalid benchmark file: {path}")
    return payload


def evaluate_case(hits: Sequence[RetrievalHit], item: Dict[str, Any]) -> Dict[str, Any]:
    case_kind = str(item.get("kind") or "positive")
    expected_any = item.get("expected_any") or []
    expected_score = evaluate_hits(hits, expected_any)
    forbidden_score = evaluate_forbidden_hits(
        hits,
        list(item.get("forbidden_any") or []) + list(item.get("expected_absent") or []),
    )

    if case_kind in {"negative", "exclusion"} and not expected_any:
        expected_ok = True
        rank = None
    else:
        expected_ok = expected_score["ok"]
        rank = expected_score["rank"]

    return {
        "ok": bool(expected_ok and forbidden_score["ok"]),
        "expected_ok": bool(expected_ok),
        "forbidden_ok": bool(forbidden_score["ok"]),
        "rank": rank,
        "forbidden_hits": forbidden_score["hits"],
    }


def evaluate_hits(hits: Sequence[RetrievalHit], expected_any: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    if not expected_any:
        return {"ok": True, "rank": None}
    for rank, hit in enumerate(hits, start=1):
        if any(hit_matches_expectation(hit, expected) for expected in expected_any):
            return {"ok": True, "rank": rank}
    return {"ok": False, "rank": None}


def evaluate_forbidden_hits(hits: Sequence[RetrievalHit], forbidden_any: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    forbidden_hits: List[Dict[str, Any]] = []
    if not forbidden_any:
        return {"ok": True, "hits": forbidden_hits}
    for rank, hit in enumerate(hits, start=1):
        for expected in forbidden_any:
            if hit_matches_expectation(hit, expected):
                forbidden_hits.append(
                    {
                        "rank": rank,
                        "document_id": hit.document_id,
                        "source_id": hit.source_id,
                        "point_type": hit.point_type,
                        "record_type": hit.record_type,
                        "citation": hit.citation,
                        "qa_status": hit.qa_status,
                        "qa_flags": hit.qa_flags,
                        "quality_flags": hit.quality_flags,
                        "requires_review": hit.requires_review,
                        "usable_for_ranking": hit.usable_for_ranking,
                        "matched": expected,
                    }
                )
    return {"ok": not forbidden_hits, "hits": forbidden_hits}


def evaluate_query_plan(query_plan: Any, expected_plan: Dict[str, Any]) -> Dict[str, Any]:
    if not expected_plan:
        return {"ok": True, "checks": {}}
    if query_plan is None:
        return {"ok": False, "checks": {"query_plan": False}}
    checks: Dict[str, bool] = {}
    plan = query_plan.model_dump(mode="json") if hasattr(query_plan, "model_dump") else dict(query_plan)
    for key in ["intents", "record_type_priorities", "point_type_priorities"]:
        expected_values = expected_plan.get(key)
        if expected_values is None:
            continue
        actual_values = plan.get(key) or []
        checks[key] = all(value in actual_values for value in expected_values)
    return {"ok": all(checks.values()) if checks else True, "checks": checks}


def hit_matches_expectation(hit: RetrievalHit, expected: Dict[str, Any]) -> bool:
    if expected.get("document_id") and hit.document_id != expected["document_id"]:
        return False
    if expected.get("source_id") and hit.source_id != expected["source_id"]:
        return False
    if expected.get("source_evidence_id") and hit.source_evidence_id != expected["source_evidence_id"]:
        return False
    if expected.get("source_id_contains") and str(expected["source_id_contains"]).lower() not in hit.source_id.lower():
        return False
    if expected.get("citation") and hit.citation != expected["citation"]:
        return False
    if expected.get("citation_contains") and str(expected["citation_contains"]).lower() not in str(hit.citation or "").lower():
        return False
    if expected.get("point_type") and hit.point_type != expected["point_type"]:
        return False
    if expected.get("record_type") and hit.record_type != expected["record_type"]:
        return False
    if expected.get("candidate_source") and hit.candidate_source != expected["candidate_source"]:
        return False
    if expected.get("curation_status") and hit.curation_status != expected["curation_status"]:
        return False
    if "page_start" in expected and hit.page_start != expected["page_start"]:
        return False
    if "page_end" in expected and hit.page_end != expected["page_end"]:
        return False
    if expected.get("qa_status") and hit.qa_status != expected["qa_status"]:
        return False
    if "requires_review" in expected and hit.requires_review != bool(expected["requires_review"]):
        return False
    if "usable_for_ranking" in expected and hit.usable_for_ranking != bool(expected["usable_for_ranking"]):
        return False
    if expected.get("quality_flags_any") and not overlaps(hit.quality_flags, expected["quality_flags_any"]):
        return False
    if expected.get("quality_flags_all") and not contains_all(hit.quality_flags, expected["quality_flags_all"]):
        return False
    if expected.get("qa_flags_any") and not overlaps(hit.qa_flags, expected["qa_flags_any"]):
        return False
    if expected.get("qa_flags_all") and not contains_all(hit.qa_flags, expected["qa_flags_all"]):
        return False
    if expected.get("review_reasons_any") and not overlaps(hit.review_reasons, expected["review_reasons_any"]):
        return False
    if expected.get("route_labels_any") and not overlaps(hit.route_labels, expected["route_labels_any"]):
        return False
    text_contains = expected.get("text_contains")
    if text_contains and str(text_contains).lower() not in hit_search_text(hit).lower():
        return False
    text_contains_any = expected.get("text_contains_any") or []
    if text_contains_any and not any(str(value).lower() in hit_search_text(hit).lower() for value in text_contains_any):
        return False
    text_contains_all = expected.get("text_contains_all") or []
    if text_contains_all and not all(str(value).lower() in hit_search_text(hit).lower() for value in text_contains_all):
        return False
    text_not_contains = expected.get("text_not_contains") or []
    if text_not_contains and any(str(value).lower() in hit_search_text(hit).lower() for value in text_not_contains):
        return False
    return True


def overlaps(actual: Iterable[Any], expected: Iterable[Any]) -> bool:
    actual_values = {str(value) for value in actual}
    return any(str(value) in actual_values for value in expected)


def contains_all(actual: Iterable[Any], expected: Iterable[Any]) -> bool:
    actual_values = {str(value) for value in actual}
    return all(str(value) in actual_values for value in expected)


def hit_search_text(hit: RetrievalHit) -> str:
    return "\n".join(
        [
            hit.text or "",
            json.dumps(hit.extracted, ensure_ascii=False, sort_keys=True),
            json.dumps(hit.metrics, ensure_ascii=False, sort_keys=True),
        ]
    )


def summarize_results(name: str, collection: str, results: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    positive_like = [item for item in results if item.get("kind", "positive") not in {"negative", "exclusion"}]
    ranks = [item["rank"] for item in positive_like if isinstance(item.get("rank"), int)]
    passed = sum(1 for item in results if item.get("ok"))
    positive_like_passed = sum(1 for item in positive_like if item.get("ok"))
    plan_passed = sum(1 for item in results if item.get("plan_ok"))
    total = len(results)
    by_kind = summarize_by_kind(results)
    return {
        "benchmark": name,
        "collection": collection,
        "total": total,
        "passed": passed,
        "plan_passed": plan_passed,
        "failed": total - passed,
        "case_pass_rate": passed / total if total else 0.0,
        "positive_like_total": len(positive_like),
        "positive_like_passed": positive_like_passed,
        "positive_like_recall_at_k": positive_like_passed / len(positive_like) if positive_like else 0.0,
        "recall_at_k": passed / total if total else 0.0,
        "plan_accuracy": plan_passed / total if total else 0.0,
        "mrr": sum(1.0 / rank for rank in ranks) / len(positive_like) if positive_like else 0.0,
        "by_kind": by_kind,
        "all_passed": passed == total,
        "results": list(results),
    }


def summarize_by_kind(results: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    summary: Dict[str, Any] = {}
    kinds = sorted({str(item.get("kind") or "positive") for item in results})
    for kind in kinds:
        items = [item for item in results if str(item.get("kind") or "positive") == kind]
        ranks = [item["rank"] for item in items if isinstance(item.get("rank"), int)]
        passed = sum(1 for item in items if item.get("ok"))
        plan_passed = sum(1 for item in items if item.get("plan_ok"))
        total = len(items)
        summary[kind] = {
            "total": total,
            "passed": passed,
            "failed": total - passed,
            "pass_rate": passed / total if total else 0.0,
            "plan_accuracy": plan_passed / total if total else 0.0,
            "mrr": sum(1.0 / rank for rank in ranks) / total if total else 0.0,
        }
    return summary


def write_summary(path: Path, summary: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def print_human_summary(summary: Dict[str, Any]) -> None:
    print(f"Benchmark: {summary['benchmark']}")
    print(f"Collection: {summary['collection']}")
    print(
        f"Passed: {summary['passed']}/{summary['total']} "
        f"PassRate={summary['case_pass_rate']:.3f} "
        f"PositiveRecall@k={summary['positive_like_recall_at_k']:.3f} MRR={summary['mrr']:.3f} "
        f"PlanAcc={summary['plan_accuracy']:.3f}"
    )
    for kind, metrics in summary.get("by_kind", {}).items():
        print(
            f"  {kind}: {metrics['passed']}/{metrics['total']} "
            f"PassRate={metrics['pass_rate']:.3f} MRR={metrics['mrr']:.3f}"
        )
    for item in summary["results"]:
        status = "OK" if item.get("ok") else "FAIL"
        rank = item.get("rank") or "-"
        print(f"{status} {item.get('kind', 'positive')} {item['id']} rank={rank}")
        if item.get("error"):
            print(f"  error={item['error']}", file=sys.stderr)
        if item.get("forbidden_hits"):
            print(f"  forbidden_hits={item['forbidden_hits']}", file=sys.stderr)


if __name__ == "__main__":
    main()
