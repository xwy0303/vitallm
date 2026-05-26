from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
for import_root in [REPO_ROOT, SRC_ROOT]:
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from enzyme_recommender.generators import GenerationResponse
from enzyme_recommender.rag.retrieval import RetrievalHit, RetrievalResponse
from enzyme_recommender.recommendation import (
    EnzymeRecommendationRequest,
    FormulationOptimizationRequest,
    FormulationOptimizationService,
    RecommendationService,
)
from enzyme_recommender.runtime import RuntimeServices
from scripts.benchmark_retrieval import evaluate_query_plan, hit_matches_expectation


NO_ANSWER_PATTERNS = [
    re.compile(pattern, re.I)
    for pattern in [
        r"证据不足",
        r"无法.*回答",
        r"没有.*相关",
        r"not enough evidence",
        r"insufficient evidence",
        r"cannot answer",
    ]
]

CASE_DEFAULTS: Dict[str, Any] = {
    "expected_evidence": [],
    "forbidden_evidence": [],
    "expected_answer_facts": [],
    "forbidden_claims": [],
    "expected_behavior": {},
}
NEW_CASE_REQUIRED_FIELDS = {
    "id",
    "kind",
    "query",
    "endpoint",
    "top_k",
    "expected_evidence",
    "forbidden_evidence",
    "expected_answer_facts",
    "forbidden_claims",
    "expected_behavior",
    "difficulty",
    "source",
    "construction_note",
    "literature_rewrite",
}
CASE_KINDS = {
    "positive",
    "ambiguous",
    "negative",
    "exclusion",
    "no_answer",
    "answer_quality",
    "formulation",
}
CASE_ENDPOINTS = {"search_evidence", "recommend", "recommend_stream", "optimize"}
CASE_DIFFICULTIES = {"easy", "medium", "hard", "adversarial"}
CASE_SOURCES = {"manual_user_like", "literature_derived", "adversarial", "regression_bug"}
ACCEPTANCE_TARGETS = [
    ("retrieval", "recall_at_5", ">=", 0.95, "Recall@5 >= 0.95"),
    ("retrieval", "mrr_at_5", ">=", 0.85, "MRR@5 >= 0.85"),
    ("retrieval", "forbidden_hit_rate", "==", 0.0, "Forbidden Hit Rate = 0"),
    ("no_answer", "no_answer_accuracy", "==", 1.0, "NoAnswer Accuracy = 1.00"),
    ("no_answer", "unexpected_candidate_rate", "==", 0.0, "Unexpected Candidate Rate = 0"),
    ("no_answer", "unexpected_citation_rate", "==", 0.0, "Unexpected Citation Rate = 0"),
    ("answer_quality", "citation_accuracy", ">=", 0.90, "Citation Accuracy >= 0.90"),
    (
        "answer_quality",
        "unsupported_claim_count_per_answer",
        "<=",
        0.10,
        "Unsupported Claim Count <= 0.10 / answer",
    ),
    ("answer_quality", "condition_type_accuracy", ">=", 0.90, "Condition Type Accuracy >= 0.90"),
    ("answer_quality", "stream_final_consistency", ">=", 0.98, "Stream/Final Consistency >= 0.98"),
    ("formulation", "evidence_backed_change_rate", ">=", 0.90, "Evidence-backed Change Rate >= 0.90"),
    ("formulation", "unsafe_global_optimum_claim_count", "==", 0.0, "Unsafe Global Optimum Claim Count = 0"),
]
UNSAFE_GLOBAL_OPTIMUM_PATTERNS = [
    re.compile(pattern, re.I)
    for pattern in [
        r"全局最优",
        r"唯一最佳",
        r"保证\s*100\s*%",
        r"global optimum",
        r"guarantee[s]?\s*100\s*%",
    ]
]


@dataclass
class EndpointResult:
    endpoint: str
    evidence_hits: List[RetrievalHit] = field(default_factory=list)
    query_plan: Any = None
    generated_text: str = ""
    stream_text: str = ""
    candidates: List[Dict[str, Any]] = field(default_factory=list)
    changes: List[Dict[str, Any]] = field(default_factory=list)
    citations: List[str] = field(default_factory=list)
    next_experiment_suggestions: List[Dict[str, Any]] = field(default_factory=list)
    raw_response: Dict[str, Any] = field(default_factory=dict)
    generation_skipped: bool = False
    error: Optional[str] = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run layered QA benchmarks for the enzyme immobilization RAG system.")
    parser.add_argument(
        "--benchmark",
        action="append",
        default=[],
        type=Path,
        help="Benchmark manifest path. Repeat to run multiple manifests.",
    )
    parser.add_argument("--config", default=Path("configs/local.yaml"), type=Path)
    parser.add_argument("--collection", default=None)
    parser.add_argument("--top-k", default=None, type=int)
    parser.add_argument(
        "--generation-mode",
        choices=["mock", "real", "skip"],
        default="mock",
        help="mock keeps benchmarks local and deterministic; real uses configured provider; skip retrieves only.",
    )
    parser.add_argument("--output", default=None, type=Path, help="Write JSON audit report.")
    parser.add_argument("--markdown", default=None, type=Path, help="Write Markdown summary report.")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--allow-failures", action="store_true")
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate benchmark manifests and exit without loading runtime services.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    benchmark_paths = args.benchmark or [
        Path("benchmarks/retrieval_quality_v1.json"),
        Path("benchmarks/answer_quality_v1.json"),
        Path("benchmarks/no_answer_intent_v1.json"),
        Path("benchmarks/formulation_optimizer_v1.json"),
    ]
    manifests = [load_manifest(path) for path in benchmark_paths]
    if args.validate_only:
        validation_summary = summarize_manifest_validation(manifests)
        if args.output:
            write_json(args.output, validation_summary)
        if args.markdown:
            write_text(args.markdown, render_manifest_validation_markdown(validation_summary))
        if args.json:
            print(json.dumps(validation_summary, ensure_ascii=False, indent=2))
        else:
            print_manifest_validation_summary(validation_summary)
        return

    runtime = RuntimeServices.from_config_file(args.config)
    if args.collection:
        runtime.config.vector_store.collection = args.collection
    if args.generation_mode == "mock":
        runtime.config.generator.provider = "mock"

    started_at = datetime.now(timezone.utc)
    case_results = []
    for manifest in manifests:
        defaults = manifest.get("defaults") or {}
        for case in manifest_cases(manifest):
            merged_case = effective_case(defaults, case)
            if args.top_k is not None:
                merged_case["top_k"] = args.top_k
            result = run_case(runtime, merged_case, args.generation_mode)
            case_results.append(
                {
                    "benchmark": manifest.get("name"),
                    "id": merged_case.get("id"),
                    "kind": merged_case.get("kind", "positive"),
                    "difficulty": merged_case.get("difficulty", "medium"),
                    "endpoint": merged_case.get("endpoint", "search_evidence"),
                    "query": merged_case.get("query"),
                    "ok": result["ok"],
                    "checks": result["checks"],
                    "metrics": result["metrics"],
                    "actual": result["actual"],
                }
            )
    summary = summarize_all(manifests, case_results, runtime, args.generation_mode, started_at)

    if args.output:
        write_json(args.output, summary)
    if args.markdown:
        write_text(args.markdown, render_markdown(summary))
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print_human_summary(summary)
    if not summary["all_passed"] and not args.allow_failures:
        raise SystemExit(2)


def load_manifest(path: Path) -> Dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"benchmark manifest must be an object: {path}")
    if not isinstance(payload.get("cases"), list) and not isinstance(payload.get("queries"), list):
        raise ValueError(f"benchmark manifest must contain cases or queries: {path}")
    validate_manifest(payload, path)
    payload["_path"] = str(path)
    return payload


def effective_case(defaults: Dict[str, Any], case: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(CASE_DEFAULTS)
    merged.update(defaults or {})
    merged.update(case)
    return merged


def validate_manifest(manifest: Dict[str, Any], path: Path) -> None:
    if manifest.get("queries") is not None and manifest.get("cases") is None:
        # Legacy retrieval_smoke manifests predate the layered QA schema.
        return
    defaults = manifest.get("defaults") or {}
    for index, raw_case in enumerate(manifest.get("cases") or []):
        if not isinstance(raw_case, dict):
            raise ValueError(f"{path}: cases[{index}] must be an object")
        case = effective_case(defaults, raw_case)
        case_label = str(case.get("id") or f"cases[{index}]")
        missing = sorted(field for field in NEW_CASE_REQUIRED_FIELDS if field not in case)
        if missing:
            raise ValueError(f"{path}:{case_label} missing required fields after defaults: {missing}")
        validate_case_schema(case, path, case_label)


def validate_case_schema(case: Dict[str, Any], path: Path, case_label: str) -> None:
    if case["kind"] not in CASE_KINDS:
        raise ValueError(f"{path}:{case_label} unsupported kind: {case['kind']}")
    if case["endpoint"] not in CASE_ENDPOINTS:
        raise ValueError(f"{path}:{case_label} unsupported endpoint: {case['endpoint']}")
    if case["difficulty"] not in CASE_DIFFICULTIES:
        raise ValueError(f"{path}:{case_label} unsupported difficulty: {case['difficulty']}")
    if case["source"] not in CASE_SOURCES:
        raise ValueError(f"{path}:{case_label} unsupported source: {case['source']}")
    if not isinstance(case["id"], str) or not case["id"].strip():
        raise ValueError(f"{path}:{case_label} id must be a non-empty string")
    if not isinstance(case["query"], str) or not case["query"].strip():
        raise ValueError(f"{path}:{case_label} query must be a non-empty string")
    if not isinstance(case["top_k"], int) or not 1 <= case["top_k"] <= 100:
        raise ValueError(f"{path}:{case_label} top_k must be an integer in [1, 100]")
    if not isinstance(case["literature_rewrite"], bool):
        raise ValueError(f"{path}:{case_label} literature_rewrite must be a boolean")
    for field_name in ["expected_evidence", "forbidden_evidence", "expected_answer_facts", "forbidden_claims"]:
        if not isinstance(case[field_name], list):
            raise ValueError(f"{path}:{case_label} {field_name} must be a list")
    if not isinstance(case["expected_behavior"], (dict, str)):
        raise ValueError(f"{path}:{case_label} expected_behavior must be an object or string")
    if case["source"] == "literature_derived" and not case["literature_rewrite"]:
        raise ValueError(f"{path}:{case_label} literature_derived cases must set literature_rewrite=true")
    if case["kind"] in {"positive", "ambiguous", "answer_quality", "formulation"}:
        min_expected = int(normalize_behavior(case.get("expected_behavior")).get("min_expected_evidence", 1))
        if min_expected > 0 and not case["expected_evidence"]:
            raise ValueError(f"{path}:{case_label} positive/answer/formulation cases need expected_evidence")
    behavior = normalize_behavior(case.get("expected_behavior"))
    if int(behavior.get("min_expected_evidence", 0)) >= 2 and len(case["expected_evidence"]) < 2:
        raise ValueError(f"{path}:{case_label} cross-evidence cases need at least 2 expected_evidence items")
    if case["kind"] == "no_answer" or behavior.get("type") == "no_answer":
        required_no_answer = {
            "type": "no_answer",
            "max_evidence_hits": 0,
            "expect_no_candidates": True,
            "expect_no_citations": True,
            "expect_no_next_experiments": True,
        }
        for key, expected_value in required_no_answer.items():
            if behavior.get(key) != expected_value:
                raise ValueError(f"{path}:{case_label} no-answer behavior must assert {key}={expected_value!r}")


def manifest_cases(manifest: Dict[str, Any]) -> List[Dict[str, Any]]:
    cases = manifest.get("cases")
    if isinstance(cases, list):
        return cases
    legacy = []
    for item in manifest.get("queries") or []:
        converted = dict(item)
        converted.setdefault("endpoint", "search_evidence")
        converted["expected_evidence"] = converted.pop("expected_any", converted.get("expected_evidence", []))
        converted["forbidden_evidence"] = list(converted.pop("forbidden_any", [])) + list(
            converted.pop("expected_absent", [])
        )
        legacy.append(converted)
    return legacy


def run_case(runtime: RuntimeServices, case: Dict[str, Any], generation_mode: str) -> Dict[str, Any]:
    try:
        endpoint_result = execute_endpoint(runtime, case, generation_mode)
    except Exception as exc:
        endpoint_result = EndpointResult(endpoint=case.get("endpoint", "search_evidence"), error=str(exc))
    checks = evaluate_endpoint_result(endpoint_result, case)
    metrics = collect_case_metrics(endpoint_result, case, checks)
    return {
        "ok": checks["overall_ok"],
        "checks": checks,
        "metrics": metrics,
        "actual": compact_actual(endpoint_result),
    }


def execute_endpoint(runtime: RuntimeServices, case: Dict[str, Any], generation_mode: str) -> EndpointResult:
    endpoint = case.get("endpoint", "search_evidence")
    top_k = int(case.get("top_k") or runtime.config.retrieval.top_k)
    usable_only = bool(case.get("usable_only", runtime.config.retrieval.usable_only))
    query = str(case.get("query") or "").strip()
    if endpoint == "search_evidence":
        response = runtime.retriever().retrieve(
            query=query,
            top_k=top_k,
            point_type=case.get("point_type"),
            usable_only=usable_only,
        )
        return EndpointResult(endpoint=endpoint, evidence_hits=response.hits, query_plan=response.query_plan)

    if endpoint in {"recommend", "recommend_stream"}:
        service = RecommendationService(runtime)
        request = EnzymeRecommendationRequest(
            enzyme_name=str(case.get("enzyme_name") or query or "lipase"),
            objective=str(case.get("objective") or "recommend_best_immobilization_agent"),
            application_context=case.get("application_context", query),
            constraints=list(case.get("constraints") or []),
            top_k=top_k,
        )
        retrieval = service.retrieve_evidence(request)
        if generation_mode == "skip":
            return EndpointResult(
                endpoint=endpoint,
                evidence_hits=retrieval.hits,
                query_plan=retrieval.query_plan,
                generation_skipped=True,
            )
        if endpoint == "recommend_stream":
            generation = run_stream_generation(service, request, retrieval)
            stream_text = generation.content
        else:
            generation = runtime.generator().generate(service.build_generation_request(request, retrieval))
            stream_text = ""
        response = service.build_response(request, retrieval, generation)
        payload = response.model_dump(mode="json")
        return EndpointResult(
            endpoint=endpoint,
            evidence_hits=retrieval.hits,
            query_plan=retrieval.query_plan,
            generated_text=response.generation_content,
            stream_text=stream_text,
            candidates=[dict(item) for item in payload.get("candidates", [])],
            citations=collect_citations(payload.get("candidates", [])),
            next_experiment_suggestions=list(payload.get("next_experiment_suggestions") or []),
            raw_response=payload,
        )

    if endpoint == "optimize":
        service = FormulationOptimizationService(runtime)
        request = FormulationOptimizationRequest(
            enzyme_name=str(case.get("enzyme_name") or query or "lipase"),
            user_formulation=dict(case.get("user_formulation") or {"note": query}),
            objective=str(case.get("objective") or "optimize_formulation"),
            application_context=case.get("application_context", query),
            constraints=list(case.get("constraints") or []),
            top_k=top_k,
        )
        retrieval = service.retrieve_evidence(request)
        if generation_mode == "skip":
            return EndpointResult(
                endpoint=endpoint,
                evidence_hits=retrieval.hits,
                query_plan=retrieval.query_plan,
                generation_skipped=True,
            )
        generation = runtime.generator().generate(service.build_generation_request(request, retrieval))
        response = service.build_response(request, retrieval, generation)
        payload = response.model_dump(mode="json")
        return EndpointResult(
            endpoint=endpoint,
            evidence_hits=retrieval.hits,
            query_plan=retrieval.query_plan,
            generated_text=response.generation_content,
            changes=[dict(item) for item in payload.get("changes", [])],
            citations=collect_citations(payload.get("changes", [])),
            next_experiment_suggestions=list(payload.get("next_experiment_suggestions") or []),
            raw_response=payload,
        )

    raise ValueError(f"unsupported benchmark endpoint: {endpoint}")


def run_stream_generation(
    service: RecommendationService,
    request: EnzymeRecommendationRequest,
    retrieval: RetrievalResponse,
) -> GenerationResponse:
    generation_request = service.build_stream_generation_request(request, retrieval)
    generator = service.runtime.generator()
    content = ""
    finish_reason = None
    usage: Dict[str, Any] = {}
    for chunk in generator.stream_generate(generation_request):
        content += chunk.delta
        if chunk.finish_reason:
            finish_reason = chunk.finish_reason
        if chunk.usage:
            usage.update(chunk.usage)
    return GenerationResponse(
        provider=getattr(generator, "provider", "unknown"),
        model=generation_request.model,
        content=content,
        finish_reason=finish_reason,
        usage=usage,
    )


def evaluate_endpoint_result(endpoint_result: EndpointResult, case: Dict[str, Any]) -> Dict[str, Any]:
    if endpoint_result.error:
        return {
            "overall_ok": False,
            "error": endpoint_result.error,
            "evidence_ok": False,
            "forbidden_ok": False,
        }

    expected_evidence = list(case.get("expected_evidence") or case.get("expected_any") or [])
    forbidden_evidence = list(case.get("forbidden_evidence") or []) + list(case.get("forbidden_any") or [])
    expected_ranks = match_expected_evidence(endpoint_result.evidence_hits, expected_evidence)
    forbidden_hits = match_forbidden_evidence(endpoint_result.evidence_hits, forbidden_evidence)
    behavior = normalize_behavior(case.get("expected_behavior"))
    min_expected_evidence = int(behavior.get("min_expected_evidence", 1 if expected_evidence else 0))
    evidence_ok = len(expected_ranks) >= min_expected_evidence
    forbidden_ok = not forbidden_hits
    plan_score = evaluate_query_plan(endpoint_result.query_plan, case.get("expected_plan") or {})

    text = searchable_response_text(endpoint_result)
    expected_facts = [str(item) for item in case.get("expected_answer_facts") or []]
    expected_fact_hits = [fact for fact in expected_facts if fact.lower() in text.lower()]
    min_expected_facts = int(behavior.get("min_expected_facts", len(expected_facts) if expected_facts else 0))
    facts_ok = len(expected_fact_hits) >= min_expected_facts

    forbidden_claims = [str(item) for item in case.get("forbidden_claims") or []]
    forbidden_claim_hits = [claim for claim in forbidden_claims if claim.lower() in text.lower()]
    forbidden_claims_ok = not forbidden_claim_hits

    citation_ok = evaluate_citation_check(endpoint_result, behavior)
    no_answer = evaluate_no_answer(endpoint_result, behavior, text)
    condition_ok = evaluate_condition_type_check(text, behavior)
    stream_final_ok = evaluate_stream_final_consistency(endpoint_result, behavior)
    formulation_ok = evaluate_formulation_check(endpoint_result, case, behavior)
    unsafe_claims = count_pattern_hits(text, UNSAFE_GLOBAL_OPTIMUM_PATTERNS)
    unsafe_ok = unsafe_claims == 0 if behavior.get("forbid_global_optimum", True) else True

    kind = str(case.get("kind") or "positive")
    if kind in {"no_answer", "negative"} or behavior.get("type") == "no_answer":
        overall = forbidden_ok and no_answer["ok"] and forbidden_claims_ok and stream_final_ok and unsafe_ok
    elif kind == "formulation" or endpoint_result.endpoint == "optimize":
        overall = (
            evidence_ok
            and forbidden_ok
            and formulation_ok["ok"]
            and forbidden_claims_ok
            and citation_ok
            and unsafe_ok
        )
    else:
        overall = (
            evidence_ok
            and forbidden_ok
            and plan_score["ok"]
            and facts_ok
            and forbidden_claims_ok
            and citation_ok
            and condition_ok
            and stream_final_ok
            and unsafe_ok
        )

    return {
        "overall_ok": bool(overall),
        "evidence_ok": bool(evidence_ok),
        "expected_evidence_matched": len(expected_ranks),
        "expected_evidence_total": len(expected_evidence),
        "expected_evidence_ranks": expected_ranks,
        "forbidden_ok": bool(forbidden_ok),
        "forbidden_hits": forbidden_hits,
        "plan_ok": bool(plan_score["ok"]),
        "plan_checks": plan_score["checks"],
        "facts_ok": bool(facts_ok),
        "expected_fact_hits": expected_fact_hits,
        "expected_facts_total": len(expected_facts),
        "forbidden_claims_ok": bool(forbidden_claims_ok),
        "forbidden_claim_hits": forbidden_claim_hits,
        "citation_ok": bool(citation_ok),
        "no_answer_ok": bool(no_answer["ok"]),
        "no_answer_checks": no_answer,
        "condition_type_ok": bool(condition_ok),
        "stream_final_consistency_ok": bool(stream_final_ok),
        "formulation_ok": bool(formulation_ok["ok"]),
        "formulation_checks": formulation_ok,
        "unsafe_global_optimum_claims": unsafe_claims,
        "unsafe_global_optimum_ok": bool(unsafe_ok),
    }


def normalize_behavior(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        return {"type": value}
    return {}


def match_expected_evidence(hits: Sequence[RetrievalHit], expected: Sequence[Dict[str, Any]]) -> List[int]:
    ranks: List[int] = []
    matched_expected: set[int] = set()
    for rank, hit in enumerate(hits, start=1):
        for index, expectation in enumerate(expected):
            if index in matched_expected:
                continue
            if hit_matches_expectation(hit, expectation):
                ranks.append(rank)
                matched_expected.add(index)
                break
    return ranks


def match_forbidden_evidence(hits: Sequence[RetrievalHit], forbidden: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    matches = []
    for rank, hit in enumerate(hits, start=1):
        for expectation in forbidden:
            if hit_matches_expectation(hit, expectation):
                matches.append(
                    {
                        "rank": rank,
                        "document_id": hit.document_id,
                        "source_id": hit.source_id,
                        "citation": hit.citation,
                        "record_type": hit.record_type,
                        "matched": expectation,
                    }
                )
    return matches


def evaluate_citation_check(endpoint_result: EndpointResult, behavior: Dict[str, Any]) -> bool:
    if endpoint_result.generation_skipped:
        return True
    requires_citations = bool(behavior.get("requires_citations"))
    if requires_citations and not endpoint_result.citations:
        return False
    if not endpoint_result.citations:
        return True
    retrieved_citations = {hit.citation for hit in endpoint_result.evidence_hits if hit.citation}
    return all(citation in retrieved_citations for citation in endpoint_result.citations)


def evaluate_no_answer(endpoint_result: EndpointResult, behavior: Dict[str, Any], text: str) -> Dict[str, Any]:
    if behavior.get("type") != "no_answer":
        return {"ok": True, "applied": False}
    max_hits = int(behavior.get("max_evidence_hits", 0))
    expect_no_candidates = bool(behavior.get("expect_no_candidates", True))
    expect_no_citations = bool(behavior.get("expect_no_citations", True))
    expect_no_next = bool(behavior.get("expect_no_next_experiments", True))
    required_no_answer_text = bool(behavior.get("requires_no_answer_text", False))
    checks = {
        "retrieval": len(endpoint_result.evidence_hits) <= max_hits,
        "candidates": not endpoint_result.candidates if expect_no_candidates else True,
        "citations": not endpoint_result.citations if expect_no_citations else True,
        "next_experiments": not endpoint_result.next_experiment_suggestions if expect_no_next else True,
        "text": has_no_answer_text(text) if required_no_answer_text else True,
    }
    return {"ok": all(checks.values()), "applied": True, "checks": checks}


def evaluate_condition_type_check(text: str, behavior: Dict[str, Any]) -> bool:
    required_terms = [str(item) for item in behavior.get("condition_type_terms") or []]
    if not required_terms:
        return True
    lower = text.lower()
    return all(term.lower() in lower for term in required_terms)


def evaluate_stream_final_consistency(endpoint_result: EndpointResult, behavior: Dict[str, Any]) -> bool:
    if endpoint_result.endpoint != "recommend_stream":
        return True
    text = endpoint_result.stream_text or endpoint_result.generated_text
    stream_says_no_answer = has_no_answer_text(text)
    if stream_says_no_answer and endpoint_result.candidates:
        return False
    if behavior.get("type") == "no_answer" and endpoint_result.candidates:
        return False
    return True


def evaluate_formulation_check(endpoint_result: EndpointResult, case: Dict[str, Any], behavior: Dict[str, Any]) -> Dict[str, Any]:
    expected_changes = list(case.get("expected_changes") or [])
    if not expected_changes and endpoint_result.endpoint != "optimize":
        return {"ok": True, "applied": False}
    matched = []
    for expected in expected_changes:
        for change in endpoint_result.changes:
            if change_matches_expected(change, expected):
                matched.append(expected)
                break
    min_expected = int(behavior.get("min_expected_changes", len(expected_changes) if expected_changes else 0))
    if endpoint_result.changes:
        backed = [
            change
            for change in endpoint_result.changes
            if change.get("evidence_ids") or change.get("citations")
        ]
        evidence_backed_rate = len(backed) / len(endpoint_result.changes)
    else:
        evidence_backed_rate = 0.0
    required_backed_rate = float(behavior.get("min_evidence_backed_change_rate", 0.0))
    ok = len(matched) >= min_expected and evidence_backed_rate >= required_backed_rate
    return {
        "ok": ok,
        "applied": True,
        "matched_expected_changes": len(matched),
        "expected_changes_total": len(expected_changes),
        "evidence_backed_change_rate": evidence_backed_rate,
    }


def change_matches_expected(change: Dict[str, Any], expected: Dict[str, Any]) -> bool:
    field_path = expected.get("field_path")
    if field_path and change.get("field_path") != field_path:
        return False
    contains = expected.get("recommended_contains")
    if contains and str(contains).lower() not in json.dumps(change.get("recommended_value"), ensure_ascii=False).lower():
        return False
    rationale_contains = expected.get("rationale_contains")
    if rationale_contains and str(rationale_contains).lower() not in str(change.get("rationale", "")).lower():
        return False
    return True


def collect_case_metrics(endpoint_result: EndpointResult, case: Dict[str, Any], checks: Dict[str, Any]) -> Dict[str, Any]:
    ranks = checks.get("expected_evidence_ranks") or []
    first_rank = min(ranks) if ranks else None
    return {
        "first_expected_rank": first_rank,
        "recall_at_3": bool(first_rank and first_rank <= 3),
        "recall_at_5": bool(first_rank and first_rank <= 5),
        "recall_at_8": bool(first_rank and first_rank <= 8),
        "mrr_at_3": reciprocal_rank(first_rank, 3),
        "mrr_at_5": reciprocal_rank(first_rank, 5),
        "mrr_at_8": reciprocal_rank(first_rank, 8),
        "ndcg_at_5": ndcg_at_k(endpoint_result.evidence_hits, list(case.get("expected_evidence") or []), 5),
        "has_expected_evidence": bool(case.get("expected_evidence")),
        "forbidden_hit_count": len(checks.get("forbidden_hits") or []),
        "unexpected_candidate": bool(checks.get("no_answer_checks", {}).get("checks", {}).get("candidates") is False),
        "unexpected_citation": bool(checks.get("no_answer_checks", {}).get("checks", {}).get("citations") is False),
        "false_retrieval": bool(checks.get("no_answer_checks", {}).get("checks", {}).get("retrieval") is False),
        "unsupported_claim_count": len(checks.get("forbidden_claim_hits") or []),
        "citation_ok": bool(checks.get("citation_ok")),
        "condition_type_ok": bool(checks.get("condition_type_ok")),
        "stream_final_consistency_ok": bool(checks.get("stream_final_consistency_ok")),
        "unsafe_global_optimum_claims": checks.get("unsafe_global_optimum_claims", 0),
    }


def reciprocal_rank(rank: Optional[int], k: int) -> float:
    if rank is None or rank > k:
        return 0.0
    return 1.0 / rank


def ndcg_at_k(hits: Sequence[RetrievalHit], expected: Sequence[Dict[str, Any]], k: int) -> float:
    if not expected:
        return 0.0
    matched_expected: set[int] = set()
    dcg = 0.0
    for rank, hit in enumerate(hits[:k], start=1):
        for index, expectation in enumerate(expected):
            if index in matched_expected:
                continue
            if hit_matches_expectation(hit, expectation):
                dcg += 1.0 / math.log2(rank + 1)
                matched_expected.add(index)
                break
    ideal_count = min(len(expected), k)
    ideal_dcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_count + 1))
    return dcg / ideal_dcg if ideal_dcg else 0.0


def summarize_all(
    manifests: Sequence[Dict[str, Any]],
    case_results: Sequence[Dict[str, Any]],
    runtime: RuntimeServices,
    generation_mode: str,
    started_at: datetime,
) -> Dict[str, Any]:
    finished_at = datetime.now(timezone.utc)
    total = len(case_results)
    passed = sum(1 for item in case_results if item["ok"])
    metrics = aggregate_metrics(case_results)
    acceptance = evaluate_acceptance_targets(metrics)
    return {
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "generation_mode": generation_mode,
        "collection": runtime.qdrant_config().collection,
        "benchmarks": [
            {
                "name": manifest.get("name"),
                "path": manifest.get("_path"),
                "target_case_count": manifest.get("target_case_count"),
                "actual_case_count": len(manifest_cases(manifest)),
            }
            for manifest in manifests
        ],
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "pass_rate": passed / total if total else 0.0,
        "all_passed": passed == total,
        "by_kind": summarize_group(case_results, "kind"),
        "by_endpoint": summarize_group(case_results, "endpoint"),
        "by_difficulty": summarize_group(case_results, "difficulty"),
        "metrics": metrics,
        "acceptance": acceptance,
        "results": list(case_results),
    }


def summarize_manifest_validation(manifests: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    benchmark_rows = []
    total_actual = 0
    total_target = 0
    user_like_cases = 0
    literature_rewrite_cases = 0
    kind_counts: Counter[str] = Counter()
    difficulty_counts: Counter[str] = Counter()
    endpoint_counts: Counter[str] = Counter()
    source_counts: Counter[str] = Counter()
    for manifest in manifests:
        cases = manifest_cases(manifest)
        actual = len(cases)
        target = int(manifest.get("target_case_count") or actual)
        total_actual += actual
        total_target += target
        for raw_case in cases:
            case = effective_case(manifest.get("defaults") or {}, raw_case)
            kind_counts[str(case.get("kind", "positive"))] += 1
            difficulty_counts[str(case.get("difficulty", "unknown"))] += 1
            endpoint_counts[str(case.get("endpoint", "search_evidence"))] += 1
            source = str(case.get("source", "unknown"))
            source_counts[source] += 1
            if source == "manual_user_like":
                user_like_cases += 1
            if case.get("literature_rewrite"):
                literature_rewrite_cases += 1
        benchmark_rows.append(
            {
                "name": manifest.get("name"),
                "path": manifest.get("_path"),
                "target_case_count": target,
                "actual_case_count": actual,
                "coverage_ratio": actual / target if target else 0.0,
            }
        )
    return {
        "validated_at": datetime.now(timezone.utc).isoformat(),
        "ok": True,
        "benchmark_count": len(manifests),
        "target_case_count": total_target,
        "actual_case_count": total_actual,
        "coverage_ratio": total_actual / total_target if total_target else 0.0,
        "manual_user_like_ratio": user_like_cases / total_actual if total_actual else 0.0,
        "literature_rewrite_cases": literature_rewrite_cases,
        "benchmarks": benchmark_rows,
        "by_kind": dict(sorted(kind_counts.items())),
        "by_endpoint": dict(sorted(endpoint_counts.items())),
        "by_difficulty": dict(sorted(difficulty_counts.items())),
        "by_source": dict(sorted(source_counts.items())),
    }


def aggregate_metrics(case_results: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    with_expected = [item for item in case_results if item["metrics"].get("has_expected_evidence")]
    no_answer_cases = [item for item in case_results if item.get("kind") == "no_answer"]
    answer_cases = [
        item
        for item in case_results
        if item.get("kind") in {"answer_quality", "positive", "ambiguous"}
        and item.get("endpoint") in {"recommend", "recommend_stream"}
    ]
    formulation_cases = [item for item in case_results if item.get("kind") == "formulation"]
    return {
        "retrieval": {
            "cases": len(with_expected),
            "recall_at_3": average_bool(with_expected, "recall_at_3"),
            "recall_at_5": average_bool(with_expected, "recall_at_5"),
            "recall_at_8": average_bool(with_expected, "recall_at_8"),
            "mrr_at_3": average_metric(with_expected, "mrr_at_3"),
            "mrr_at_5": average_metric(with_expected, "mrr_at_5"),
            "mrr_at_8": average_metric(with_expected, "mrr_at_8"),
            "ndcg_at_5": average_metric(with_expected, "ndcg_at_5"),
            "forbidden_hit_rate": average_bool(case_results, "forbidden_hit_count", truthy=True),
            "plan_accuracy": average_check(case_results, "plan_ok"),
        },
        "no_answer": {
            "cases": len(no_answer_cases),
            "no_answer_accuracy": average_check(no_answer_cases, "no_answer_ok"),
            "false_retrieval_rate": average_bool(no_answer_cases, "false_retrieval", truthy=True),
            "unexpected_candidate_rate": average_bool(no_answer_cases, "unexpected_candidate", truthy=True),
            "unexpected_citation_rate": average_bool(no_answer_cases, "unexpected_citation", truthy=True),
        },
        "answer_quality": {
            "cases": len(answer_cases),
            "citation_accuracy": average_bool(answer_cases, "citation_ok"),
            "faithfulness": 1.0 - average_metric(answer_cases, "unsupported_claim_count"),
            "answer_relevancy": average_check(answer_cases, "facts_ok"),
            "unsupported_claim_count_per_answer": average_metric(answer_cases, "unsupported_claim_count"),
            "condition_type_accuracy": average_bool(answer_cases, "condition_type_ok"),
            "stream_final_consistency": average_bool(answer_cases, "stream_final_consistency_ok"),
        },
        "formulation": {
            "cases": len(formulation_cases),
            "field_recommendation_precision": average_formulation_precision(formulation_cases),
            "evidence_backed_change_rate": average_formulation_backing(formulation_cases),
            "unsafe_global_optimum_claim_count": sum(
                item["metrics"].get("unsafe_global_optimum_claims", 0) for item in formulation_cases
            ),
        },
    }


def evaluate_acceptance_targets(metrics: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    checks = []
    for group, metric, operator, threshold, label in ACCEPTANCE_TARGETS:
        group_metrics = metrics.get(group, {})
        if int(group_metrics.get("cases") or 0) == 0:
            checks.append(
                {
                    "group": group,
                    "metric": metric,
                    "value": None,
                    "operator": operator,
                    "threshold": threshold,
                    "label": label,
                    "ok": True,
                    "skipped": True,
                    "reason": "no cases in this run",
                }
            )
            continue
        value = float(metrics.get(group, {}).get(metric) or 0.0)
        passed = compare_metric(value, operator, threshold)
        checks.append(
            {
                "group": group,
                "metric": metric,
                "value": value,
                "operator": operator,
                "threshold": threshold,
                "label": label,
                "ok": passed,
                "skipped": False,
            }
        )
    return {
        "all_targets_met": all(item["ok"] for item in checks),
        "checks": checks,
    }


def compare_metric(value: float, operator: str, threshold: float) -> bool:
    tolerance = 1e-12
    if operator == ">=":
        return value + tolerance >= threshold
    if operator == "<=":
        return value <= threshold + tolerance
    if operator == "==":
        return abs(value - threshold) <= tolerance
    raise ValueError(f"unsupported metric operator: {operator}")


def summarize_group(case_results: Sequence[Dict[str, Any]], key: str) -> Dict[str, Any]:
    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for item in case_results:
        grouped[str(item.get(key) or "unknown")].append(item)
    return {
        group: {
            "total": len(items),
            "passed": sum(1 for item in items if item["ok"]),
            "failed": sum(1 for item in items if not item["ok"]),
            "pass_rate": sum(1 for item in items if item["ok"]) / len(items) if items else 0.0,
        }
        for group, items in sorted(grouped.items())
    }


def average_metric(items: Sequence[Dict[str, Any]], metric_key: str) -> float:
    if not items:
        return 0.0
    return sum(float(item["metrics"].get(metric_key) or 0.0) for item in items) / len(items)


def average_bool(items: Sequence[Dict[str, Any]], metric_key: str, truthy: bool = False) -> float:
    if not items:
        return 0.0
    values = []
    for item in items:
        value = item["metrics"].get(metric_key)
        if truthy:
            values.append(bool(value))
        else:
            values.append(value is True)
    return sum(1 for value in values if value) / len(values)


def average_check(items: Sequence[Dict[str, Any]], check_key: str) -> float:
    if not items:
        return 0.0
    return sum(1 for item in items if item["checks"].get(check_key) is True) / len(items)


def average_formulation_precision(items: Sequence[Dict[str, Any]]) -> float:
    values = []
    for item in items:
        checks = item["checks"].get("formulation_checks") or {}
        total = checks.get("expected_changes_total") or 0
        matched = checks.get("matched_expected_changes") or 0
        if total:
            values.append(matched / total)
    return sum(values) / len(values) if values else 0.0


def average_formulation_backing(items: Sequence[Dict[str, Any]]) -> float:
    values = []
    for item in items:
        checks = item["checks"].get("formulation_checks") or {}
        if checks.get("applied"):
            values.append(float(checks.get("evidence_backed_change_rate") or 0.0))
    return sum(values) / len(values) if values else 0.0


def compact_actual(endpoint_result: EndpointResult) -> Dict[str, Any]:
    return {
        "endpoint": endpoint_result.endpoint,
        "error": endpoint_result.error,
        "generation_skipped": endpoint_result.generation_skipped,
            "hits": [
                {
                "rank": index,
                "document_id": hit.document_id,
                "source_id": hit.source_id,
                "citation": hit.citation,
                "point_type": hit.point_type,
                "record_type": hit.record_type,
                "score": hit.score,
                "requires_review": hit.requires_review,
                "usable_for_ranking": hit.usable_for_ranking,
            }
            for index, hit in enumerate(endpoint_result.evidence_hits[:8], start=1)
        ],
        "total_evidence_hits": len(endpoint_result.evidence_hits),
        "generated_text": endpoint_result.generated_text[:1200],
        "stream_text": endpoint_result.stream_text[:1200],
        "candidates_count": len(endpoint_result.candidates),
        "changes_count": len(endpoint_result.changes),
        "citations": endpoint_result.citations,
        "next_experiment_suggestions_count": len(endpoint_result.next_experiment_suggestions),
    }


def collect_citations(items: Iterable[Any]) -> List[str]:
    citations = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        for citation in item.get("citations") or []:
            if citation:
                citations.append(str(citation))
    return sorted(set(citations))


def searchable_response_text(endpoint_result: EndpointResult) -> str:
    return "\n".join(
        [
            endpoint_result.generated_text or "",
            endpoint_result.stream_text or "",
            json.dumps(endpoint_result.candidates, ensure_ascii=False, sort_keys=True),
            json.dumps(endpoint_result.changes, ensure_ascii=False, sort_keys=True),
            json.dumps(endpoint_result.next_experiment_suggestions, ensure_ascii=False, sort_keys=True),
        ]
    )


def has_no_answer_text(text: str) -> bool:
    return any(pattern.search(text or "") for pattern in NO_ANSWER_PATTERNS)


def count_pattern_hits(text: str, patterns: Sequence[re.Pattern[str]]) -> int:
    return sum(1 for pattern in patterns if pattern.search(text or ""))


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def render_markdown(summary: Dict[str, Any]) -> str:
    lines = [
        f"# QA Benchmark Summary - {summary['finished_at']}",
        "",
        f"- Generation mode: `{summary['generation_mode']}`",
        f"- Collection: `{summary['collection']}`",
        f"- Passed: {summary['passed']}/{summary['total']} ({summary['pass_rate']:.3f})",
        "",
        "## Metrics",
        "",
        "| Group | Metric | Value |",
        "| --- | --- | ---: |",
    ]
    for group, metrics in summary["metrics"].items():
        for key, value in metrics.items():
            if isinstance(value, float):
                display = f"{value:.3f}"
            else:
                display = str(value)
            lines.append(f"| {group} | {key} | {display} |")
    lines.extend(
        [
            "",
            "## Acceptance Targets",
            "",
            "| Target | Actual | Status |",
            "| --- | ---: | --- |",
        ]
    )
    for check in summary.get("acceptance", {}).get("checks", []):
        actual = "SKIP" if check.get("skipped") else f"{check['value']:.3f}"
        status = "SKIP" if check.get("skipped") else ("PASS" if check["ok"] else "FAIL")
        lines.append(
            f"| {check['label']} | {actual} | {status} |"
        )
    lines.extend(
        [
            "",
            "## Failed Cases",
            "",
            "| Benchmark | ID | Kind | Endpoint | Failed Checks | First Hits / Counts |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
    )
    failed = [item for item in summary["results"] if not item["ok"]]
    if not failed:
        lines.append("| - | - | - | - | - | - |")
    for item in failed[:80]:
        failed_checks = [
            key
            for key, value in item["checks"].items()
            if key.endswith("_ok") and value is False
        ]
        actual = item.get("actual") or {}
        hit_refs = ", ".join(
            f"{hit.get('rank')}:{hit.get('document_id') or '-'}:{hit.get('record_type') or '-'}"
            for hit in (actual.get("hits") or [])[:3]
        )
        counts = (
            f"hits={len(actual.get('hits') or [])}; candidates={actual.get('candidates_count', 0)}; "
            f"citations={len(actual.get('citations') or [])}; changes={actual.get('changes_count', 0)}"
        )
        lines.append(
            f"| {item['benchmark']} | {item['id']} | {item['kind']} | {item['endpoint']} | "
            f"{', '.join(failed_checks) or 'overall'} | {hit_refs or counts} |"
        )
    return "\n".join(lines) + "\n"


def render_manifest_validation_markdown(summary: Dict[str, Any]) -> str:
    lines = [
        f"# QA Benchmark Manifest Validation - {summary['validated_at']}",
        "",
        f"- Benchmarks: {summary['benchmark_count']}",
        f"- Seed cases: {summary['actual_case_count']}/{summary['target_case_count']} ({summary['coverage_ratio']:.3f})",
        f"- Manual user-like ratio: {summary['manual_user_like_ratio']:.3f}",
        f"- Literature rewrite cases: {summary['literature_rewrite_cases']}",
        "",
        "## Manifests",
        "",
        "| Manifest | Target | Actual | Coverage |",
        "| --- | ---: | ---: | ---: |",
    ]
    for benchmark in summary["benchmarks"]:
        lines.append(
            f"| {benchmark['name']} | {benchmark['target_case_count']} | "
            f"{benchmark['actual_case_count']} | {benchmark['coverage_ratio']:.3f} |"
        )
    for section, values in [
        ("Kind", summary["by_kind"]),
        ("Endpoint", summary["by_endpoint"]),
        ("Difficulty", summary["by_difficulty"]),
        ("Source", summary["by_source"]),
    ]:
        lines.extend(["", f"## By {section}", "", "| Value | Count |", "| --- | ---: |"])
        for key, count in values.items():
            lines.append(f"| {key} | {count} |")
    return "\n".join(lines) + "\n"


def print_human_summary(summary: Dict[str, Any]) -> None:
    print(f"QA Benchmark: passed {summary['passed']}/{summary['total']} pass_rate={summary['pass_rate']:.3f}")
    print(f"Collection: {summary['collection']}")
    print(f"Generation mode: {summary['generation_mode']}")
    for group, metrics in summary["metrics"].items():
        compact = ", ".join(
            f"{key}={value:.3f}" if isinstance(value, float) else f"{key}={value}"
            for key, value in metrics.items()
        )
        print(f"{group}: {compact}")
    print(f"Acceptance targets met: {summary.get('acceptance', {}).get('all_targets_met')}")
    for item in summary["results"]:
        if item["ok"]:
            continue
        failed_checks = [key for key, value in item["checks"].items() if key.endswith("_ok") and value is False]
        print(
            f"FAIL {item['benchmark']}::{item['id']} kind={item['kind']} endpoint={item['endpoint']} "
            f"checks={failed_checks}",
            file=sys.stderr,
        )


def print_manifest_validation_summary(summary: Dict[str, Any]) -> None:
    print(
        "QA benchmark manifests validated: "
        f"{summary['actual_case_count']}/{summary['target_case_count']} seed cases "
        f"coverage={summary['coverage_ratio']:.3f}"
    )
    for benchmark in summary["benchmarks"]:
        print(
            f"{benchmark['name']}: actual={benchmark['actual_case_count']} "
            f"target={benchmark['target_case_count']} coverage={benchmark['coverage_ratio']:.3f}"
        )


if __name__ == "__main__":
    main()
