from __future__ import annotations

import json
import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from enzyme_recommender.generators import ChatMessage, GenerationRequest, GenerationResponse
from enzyme_recommender.rag.enzyme_aliases import matched_enzyme_alias_keys
from enzyme_recommender.rag.retrieval import (
    RetrievalHit,
    RetrievalResponse,
    build_query_plan,
    classify_no_retrieval_query,
    extract_document_ids,
)
from enzyme_recommender.runtime import RuntimeServices


class EnzymeRecommendationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    enzyme_name: str
    objective: str = "recommend_best_immobilization_agent"
    application_context: Optional[str] = None
    constraints: List[str] = Field(default_factory=list)
    top_k: Optional[int] = None

    @field_validator("enzyme_name")
    @classmethod
    def enzyme_name_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("enzyme_name must not be empty")
        return value.strip()


class RecommendedCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    rank: int
    strategy_summary: str
    carrier: Optional[str] = None
    immobilization_method: Optional[str] = None
    recommended_conditions: Dict[str, Any] = Field(default_factory=dict)
    expected_benefits: List[str] = Field(default_factory=list)
    risks: List[str] = Field(default_factory=list)
    evidence_ids: List[str] = Field(default_factory=list)
    citations: List[str] = Field(default_factory=list)
    confidence: str = "low"


class EnzymeRecommendationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    recommendation_id: str
    created_at: str
    target_enzyme: str
    objective: str
    retrieval_query: str
    generator_provider: str
    generator_model: str
    candidates: List[RecommendedCandidate]
    evidence_hits: List[RetrievalHit]
    generation_content: str
    generation_json: Optional[Dict[str, Any]] = None
    limitations: List[str] = Field(default_factory=list)
    next_experiment_suggestions: List[Dict[str, Any]] = Field(default_factory=list)


@dataclass(frozen=True)
class SpecificEnzymeAliasContext:
    alias_keys: frozenset[str] = frozenset()
    enabled: bool = False
    reason: str = "disabled"


class RecommendationService:
    def __init__(self, runtime: RuntimeServices) -> None:
        self.runtime = runtime

    def recommend_by_enzyme(self, request: EnzymeRecommendationRequest) -> EnzymeRecommendationResponse:
        retrieval = self.retrieve_evidence(request)
        generation = (
            deterministic_no_answer_generation(retrieval)
            if retrieval_guard_reason(retrieval)
            else self._generate_recommendation(request, retrieval)
        )
        return self.build_response(request, retrieval, generation)

    def retrieve_evidence(self, request: EnzymeRecommendationRequest) -> RetrievalResponse:
        guard_query = build_user_guard_query(request)
        guard_plan = build_query_plan(guard_query, top_k=request.top_k or self.runtime.config.retrieval.top_k)
        guard_reason = classify_no_retrieval_query(guard_query, guard_plan)
        if guard_reason:
            guarded_plan = guard_plan.model_copy(
                update={
                    "retrieval_guard": guard_reason,
                    "intents": dedupe_strings([*guard_plan.intents, "no_answer"]),
                }
            )
            return RetrievalResponse(
                query=guard_query,
                collection=self.runtime.qdrant_config().collection,
                embedding_model=self.runtime.embedding_model().name,
                top_k=request.top_k or self.runtime.config.retrieval.top_k,
                usable_only=self.runtime.config.retrieval.usable_only,
                query_plan=guarded_plan,
                hits=[],
            )

        retrieval_query = build_retrieval_query(request)
        return self.runtime.retriever().retrieve(
            query=retrieval_query,
            top_k=request.top_k or self.runtime.config.retrieval.top_k,
            usable_only=self.runtime.config.retrieval.usable_only,
        )

    def build_generation_request(
        self,
        request: EnzymeRecommendationRequest,
        retrieval: RetrievalResponse,
    ) -> GenerationRequest:
        config = self.runtime.config
        provider_config = config.generator_providers[config.generator.provider]
        return GenerationRequest(
            messages=[
                ChatMessage(role="system", content=SYSTEM_PROMPT),
                ChatMessage(role="user", content=build_generation_prompt(request, retrieval)),
            ],
            model=provider_config.model,
            temperature=config.generator.temperature,
            response_format="json_object",
            timeout_seconds=config.generator.timeout_seconds,
            max_retries=config.generator.max_retries,
        )

    def build_stream_generation_request(
        self,
        request: EnzymeRecommendationRequest,
        retrieval: RetrievalResponse,
    ) -> GenerationRequest:
        base_request = self.build_generation_request(request, retrieval)
        return base_request.model_copy(
            update={
                "messages": [
                    ChatMessage(role="system", content=STREAM_SYSTEM_PROMPT),
                    ChatMessage(role="user", content=build_stream_generation_prompt(request, retrieval)),
                ],
                "response_format": "text",
                "max_retries": 0,
            }
        )

    def build_response(
        self,
        request: EnzymeRecommendationRequest,
        retrieval: RetrievalResponse,
        generation: GenerationResponse,
    ) -> EnzymeRecommendationResponse:
        if retrieval_guard_reason(retrieval):
            generation = deterministic_no_answer_generation(retrieval)
        generation_json = parse_json_object(generation.content)
        alias_context = specific_enzyme_alias_context_from_request(
            enzyme_name=request.enzyme_name,
            application_context=request.application_context,
            constraints=request.constraints,
            objective=request.objective,
            retrieval=retrieval,
        )
        candidates = build_candidates_from_generation_or_evidence(generation_json, retrieval, alias_context)
        return EnzymeRecommendationResponse(
            recommendation_id=make_recommendation_id(request, retrieval),
            created_at=datetime.now(timezone.utc).isoformat(),
            target_enzyme=request.enzyme_name,
            objective=request.objective,
            retrieval_query=build_retrieval_query(request),
            generator_provider=generation.provider,
            generator_model=generation.model,
            candidates=candidates,
            evidence_hits=retrieval.hits,
            generation_content=generation.content,
            generation_json=generation_json,
            limitations=build_limitations(generation, retrieval, generation_json, alias_context),
            next_experiment_suggestions=build_next_experiment_suggestions(retrieval, generation_json, alias_context),
        )

    def _generate_recommendation(
        self,
        request: EnzymeRecommendationRequest,
        retrieval: RetrievalResponse,
    ) -> GenerationResponse:
        generator = self.runtime.generator()
        return generator.generate(self.build_generation_request(request, retrieval))


SYSTEM_PROMPT = """你是一个面向生物酶固定化的 evidence-first 推荐助手。
只允许基于给定 evidence context 输出建议。不得把“最佳固化剂”说成脱离目标、应用场景和实验条件的全局唯一答案。
输出必须是 JSON object，包含 candidates、limitations、next_experiment_suggestions。"""


STREAM_SYSTEM_PROMPT = """你是一个面向生物酶固定化的 evidence-first 推荐助手。
优先快速输出可读建议，不输出 JSON。只能基于给定 evidence context；每条关键结论必须带形如 [1]、[2] 的 reference index。"""


def build_retrieval_query(request: EnzymeRecommendationRequest) -> str:
    application_context = request.application_context or ""
    constraints = " ".join(request.constraints)
    user_text = " ".join(part for part in [application_context, constraints] if part).strip()
    parts = []
    if user_text:
        parts.append(user_text)
        if request.enzyme_name and request.enzyme_name.lower() not in user_text.lower():
            parts.append(request.enzyme_name)
    else:
        parts.append(request.enzyme_name)

    if should_expand_recommendation_query(request, user_text):
        parts.append("immobilization carrier support method conditions activity recovery reusability stability")
    else:
        parts.append("immobilization enzyme evidence")
    return " ".join(part for part in parts if part).strip()


def build_user_guard_query(request: EnzymeRecommendationRequest) -> str:
    parts = [
        request.application_context or "",
        " ".join(request.constraints),
        request.enzyme_name,
    ]
    return " ".join(part for part in parts if part).strip()


EVIDENCE_QA_OBJECTIVE = "answer_evidence_question"

RECOMMENDATION_INTENT_TERMS = {
    "recommend",
    "recommendation",
    "best",
    "optimal",
    "optimize",
    "suggest",
    "should",
    "better",
    "prefer",
    "preferred",
    "推荐",
    "最适合",
    "最佳",
    "最优",
    "优化",
    "建议",
    "应该",
    "该用",
    "更好",
    "效果好",
    "方案",
}


def should_expand_recommendation_query(request: EnzymeRecommendationRequest, user_text: str) -> bool:
    if request.objective == EVIDENCE_QA_OBJECTIVE:
        return False
    if not user_text:
        return True
    text = user_text.lower()
    return any(term in text for term in RECOMMENDATION_INTENT_TERMS)


def build_generation_prompt(request: EnzymeRecommendationRequest, retrieval: RetrievalResponse) -> str:
    if retrieval_guard_reason(retrieval):
        return "\n\n".join(
            [
                "任务：拒绝无关、低信息量或违反 evidence-first 边界的请求。",
                f"拒答原因：{retrieval_guard_reason(retrieval)}",
                "Evidence context: 无可用证据。",
                "请输出 JSON object："
                '{"candidates":[],"limitations":["no relevant enzyme immobilization evidence was retrieved"],'
                '"next_experiment_suggestions":[]}',
            ]
        )
    return "\n\n".join(
        [
            "任务：根据 evidence context 推荐酶固定化载体/固化剂，并说明证据、适用边界和下一步实验。",
            f"目标酶：{request.enzyme_name}",
            f"目标：{request.objective}",
            f"应用场景：{request.application_context or '未提供'}",
            f"用户约束：{request.constraints or '未提供'}",
            "Evidence context:",
            retrieval.context_text(max_chars_per_hit=900),
            "请输出 JSON object："
            '{"candidates":[{"rank":1,"strategy_summary":"","carrier":"","immobilization_method":"",'
            '"recommended_conditions":{},"expected_benefits":[],"risks":[],"evidence_ids":[],'
            '"citations":[],"confidence":"low|medium|high"}],"limitations":[],"next_experiment_suggestions":[]}',
        ]
    )


def build_stream_generation_prompt(request: EnzymeRecommendationRequest, retrieval: RetrievalResponse) -> str:
    if retrieval_guard_reason(retrieval):
        return "\n\n".join(
            [
                "任务：拒绝无关、低信息量或违反 evidence-first 边界的请求。",
                f"拒答原因：{retrieval_guard_reason(retrieval)}",
                "Evidence context: 无可用证据。",
                "输出要求：说明没有足够相关证据，不输出候选方案，不输出引用，不建议下一步实验。",
            ]
        )
    if request.objective == EVIDENCE_QA_OBJECTIVE:
        return "\n\n".join(
            [
                "任务：基于 evidence context 回答用户问题，不要默认改写成固定化推荐。",
                f"用户问题：{request.application_context or request.enzyme_name}",
                f"检索关键词/目标酶：{request.enzyme_name}",
                f"用户约束：{request.constraints or '未提供'}",
                "Evidence context:",
                retrieval.context_text(max_chars_per_hit=600),
                "输出要求：",
                "- 直接回答用户问题；如果 evidence 不足，明确说不足。",
                "- 每个关键事实必须带 [1]、[2] 这类 reference index。",
                "- 不要引入 evidence context 之外的新事实。",
                "- 不输出 JSON。",
            ]
        )
    return "\n\n".join(
        [
            "任务：快速给出面向前端 live stream 的首答。",
            f"目标酶：{request.enzyme_name}",
            f"目标：{request.objective}",
            f"应用场景：{request.application_context or '未提供'}",
            f"用户约束：{request.constraints or '未提供'}",
            "Evidence context:",
            retrieval.context_text(max_chars_per_hit=600),
            "输出要求：",
            "- 先给 1 句推荐结论，再给 3-5 条 bullet。",
            "- 每条 bullet 只使用 [1]、[2] 这类 reference index 引用，不要写裸 citation。",
            "- 明确适用边界和需要补实验验证的点。",
            "- 不输出 JSON，不要引入 evidence context 之外的新事实。",
        ]
    )


def retrieval_guard_reason(retrieval: RetrievalResponse) -> Optional[str]:
    if retrieval.query_plan is None:
        return None
    return retrieval.query_plan.retrieval_guard


def deterministic_no_answer_generation(retrieval: RetrievalResponse) -> GenerationResponse:
    reason = retrieval_guard_reason(retrieval) or "no_relevant_evidence"
    return GenerationResponse(
        provider="retrieval_guard",
        model="deterministic-no-answer-v1",
        content=f"证据不足：{reason}。没有检索到足够相关的脂肪酶固定化证据，不能生成候选方案。",
        finish_reason="guarded",
        usage={"guarded": True, "retrieval_guard": reason},
    )


def build_candidates_from_generation_or_evidence(
    generation_json: Optional[Dict[str, Any]],
    retrieval: RetrievalResponse,
    alias_context: Optional[SpecificEnzymeAliasContext] = None,
) -> List[RecommendedCandidate]:
    specific_alias_keys = alias_context.alias_keys if alias_context and alias_context.enabled else frozenset()
    if generation_json and isinstance(generation_json.get("candidates"), list):
        candidates = []
        for index, raw_candidate in enumerate(generation_json["candidates"], start=1):
            if not isinstance(raw_candidate, dict):
                continue
            sanitized = _sanitize_candidate(raw_candidate, retrieval)
            if not sanitized["evidence_ids"] and not sanitized["citations"]:
                continue
            if not refs_support_specific_enzyme_alias(sanitized, retrieval, specific_alias_keys):
                continue
            try:
                candidates.append(RecommendedCandidate.model_validate(sanitized))
            except ValueError:
                continue
        if candidates:
            return candidates

    evidence_candidates = []
    formulation_conditions = first_formulation_conditions(retrieval, specific_alias_keys=specific_alias_keys)
    for hit in retrieval.hits:
        if not hit_supports_specific_enzyme_alias(hit, specific_alias_keys):
            continue
        if hit.record_type not in {"immobilization_strategy", "table_comparison_row", "formulation_condition"}:
            continue
        extracted = hit.extracted
        carrier = extracted.get("carrier") or extracted.get("carrier_variant")
        method = extracted.get("immobilization_method")
        if not carrier and not method and hit.record_type != "table_comparison_row":
            continue
        evidence_candidates.append(
            RecommendedCandidate(
                rank=len(evidence_candidates) + 1,
                strategy_summary=summary_from_hit(hit),
                carrier=carrier,
                immobilization_method=method,
                recommended_conditions=merge_conditions(conditions_from_hit(hit), formulation_conditions),
                expected_benefits=benefits_from_hit(hit),
                risks=[],
                evidence_ids=[hit.source_id],
                citations=[hit.citation] if hit.citation else [],
                confidence=hit.confidence or "medium",
            )
        )
        if len(evidence_candidates) >= 3:
            break

    # Fallback: if no structured candidates were built but there are hits,
    # create a generic candidate from the top retrieval hit.
    fallback_hits = [hit for hit in retrieval.hits if hit_supports_specific_enzyme_alias(hit, specific_alias_keys)]
    if not evidence_candidates and fallback_hits:
        top = fallback_hits[0]
        evidence_candidates.append(
            RecommendedCandidate(
                rank=1,
                strategy_summary=top.text[:300] if top.text else "retrieved evidence",
                carrier=None,
                immobilization_method=None,
                recommended_conditions=first_formulation_conditions(retrieval, specific_alias_keys=specific_alias_keys),
                expected_benefits=benefits_from_hit(top),
                risks=[],
                evidence_ids=[top.source_id],
                citations=[top.citation] if top.citation else [],
                confidence=top.confidence or "low",
            )
        )

    return evidence_candidates


def first_formulation_conditions(
    retrieval: RetrievalResponse,
    specific_alias_keys: Optional[frozenset[str]] = None,
) -> Dict[str, Any]:
    for hit in retrieval.hits:
        if not hit_supports_specific_enzyme_alias(hit, specific_alias_keys or frozenset()):
            continue
        if hit.record_type == "formulation_condition" and hit.extracted:
            return dict(hit.extracted)
    return {}


def merge_conditions(primary: Dict[str, Any], fallback: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(fallback)
    merged.update(primary)
    return merged


def summary_from_hit(hit: RetrievalHit) -> str:
    extracted = hit.extracted
    if hit.record_type == "table_comparison_row":
        enzyme = extracted.get("enzyme_name") or "enzyme"
        substrate = extracted.get("substrate") or "substrate"
        acyl_acceptor = extracted.get("acyl_acceptor") or "acyl acceptor"
        return f"{enzyme} in {substrate} system with {acyl_acceptor}"
    carrier = extracted.get("carrier_variant") or extracted.get("carrier")
    method = extracted.get("immobilization_method")
    if carrier and method:
        return f"{method} on {carrier}"
    return hit.text[:180]


def conditions_from_hit(hit: RetrievalHit) -> Dict[str, Any]:
    extracted = dict(hit.extracted)
    for key in ["carrier", "carrier_variant", "immobilization_method", "material_class"]:
        extracted.pop(key, None)
    return extracted


def benefits_from_hit(hit: RetrievalHit) -> List[str]:
    benefits = []
    for metric in hit.metrics:
        name = metric.get("name")
        value = metric.get("value")
        unit = metric.get("unit")
        if name and value is not None:
            benefits.append(f"{name}: {value}{unit or ''}")
    return benefits


def build_limitations(
    generation: GenerationResponse,
    retrieval: RetrievalResponse,
    generation_json: Optional[Dict[str, Any]] = None,
    alias_context: Optional[SpecificEnzymeAliasContext] = None,
) -> List[str]:
    limitations = []
    specific_alias_keys = alias_context.alias_keys if alias_context and alias_context.enabled else frozenset()
    if generation_json:
        limitations.extend(string_items(generation_json.get("limitations")))
    if generation.provider == "mock":
        limitations.append("mock generator only validates pipeline wiring; final wording requires SiliconFlow/DeepSeek.")
    if not retrieval.hits:
        limitations.append("no usable evidence was retrieved")
    elif specific_alias_keys and not any(hit_supports_specific_enzyme_alias(hit, specific_alias_keys) for hit in retrieval.hits):
        limitations.append("no usable evidence for the requested enzyme alias was retrieved")
    if any(hit.requires_review for hit in retrieval.hits):
        limitations.append("some retrieved evidence requires review and should not be used for ranking")
    return dedupe_strings(limitations)


def build_next_experiment_suggestions(
    retrieval: RetrievalResponse,
    generation_json: Optional[Dict[str, Any]] = None,
    alias_context: Optional[SpecificEnzymeAliasContext] = None,
) -> List[Dict[str, Any]]:
    specific_alias_keys = alias_context.alias_keys if alias_context and alias_context.enabled else frozenset()
    if specific_alias_keys and not any(hit_supports_specific_enzyme_alias(hit, specific_alias_keys) for hit in retrieval.hits):
        return []
    generated = normalize_experiment_suggestions(generation_json)
    if generated:
        return generated
    if not retrieval.hits:
        return []
    return [
        {
            "variable": "enzyme_loading / carrier_amount / pH / temperature / time",
            "metric": "activity recovery, biodiesel yield, residual activity after reuse",
            "evidence_basis": [hit.citation for hit in retrieval.hits[:3] if hit.citation],
        }
    ]


def normalize_experiment_suggestions(generation_json: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not generation_json:
        return []
    raw_suggestions = generation_json.get("next_experiment_suggestions")
    if not isinstance(raw_suggestions, list):
        return []
    suggestions: List[Dict[str, Any]] = []
    for item in raw_suggestions:
        if isinstance(item, dict):
            suggestions.append(item)
        elif isinstance(item, str) and item.strip():
            suggestions.append({"suggestion": item.strip()})
    return suggestions


def string_items(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def dedupe_strings(values: List[str]) -> List[str]:
    deduped = []
    seen = set()
    for value in values:
        if value not in seen:
            deduped.append(value)
            seen.add(value)
    return deduped


def parse_json_object(value: str) -> Optional[Dict[str, Any]]:
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def make_recommendation_id(request: EnzymeRecommendationRequest, retrieval: RetrievalResponse) -> str:
    seed = "|".join([request.enzyme_name, request.objective, ",".join(hit.source_id for hit in retrieval.hits[:5])])
    digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()
    return f"rec_{digest[:12]}"


def _sanitize_candidate(candidate: Dict[str, Any], retrieval: RetrievalResponse) -> Dict[str, Any]:
    """Sanitize LLM-generated candidate to match RecommendedCandidate model constraints."""
    sanitized = dict(candidate)
    sanitized["evidence_ids"], sanitized["citations"] = resolve_evidence_refs(
        raw_ids=sanitized.get("evidence_ids"),
        raw_citations=sanitized.get("citations"),
        retrieval=retrieval,
    )
    # confidence must be a valid value
    confidence = sanitized.get("confidence")
    if confidence not in ("low", "medium", "high"):
        sanitized["confidence"] = "medium"
    return sanitized


def resolve_evidence_refs(
    raw_ids: Any,
    raw_citations: Any,
    retrieval: RetrievalResponse,
) -> tuple[List[str], List[str]]:
    hits_by_id = {hit.source_id: hit for hit in retrieval.hits}
    hits_by_citation = {hit.citation: hit for hit in retrieval.hits if hit.citation}
    evidence_ids: List[str] = []
    citations: List[str] = []

    id_items = raw_ids if isinstance(raw_ids, list) else []
    for raw_id in id_items:
        ref = str(raw_id).strip()
        hit = resolve_hit_ref(ref, retrieval, hits_by_id, hits_by_citation)
        if hit is not None:
            evidence_ids.append(hit.source_id)
            if hit.citation:
                citations.append(hit.citation)

    citation_items = raw_citations if isinstance(raw_citations, list) else []
    for raw_citation in citation_items:
        ref = str(raw_citation).strip()
        hit = resolve_hit_ref(ref, retrieval, hits_by_id, hits_by_citation)
        if hit is not None:
            evidence_ids.append(hit.source_id)
            if hit.citation:
                citations.append(hit.citation)

    return dedupe_strings(evidence_ids), dedupe_strings(citations)


def resolve_hit_ref(
    ref: str,
    retrieval: RetrievalResponse,
    hits_by_id: Dict[str, RetrievalHit],
    hits_by_citation: Dict[str, RetrievalHit],
) -> Optional[RetrievalHit]:
    if not ref:
        return None
    if ref in hits_by_id:
        return hits_by_id[ref]
    if ref in hits_by_citation:
        return hits_by_citation[ref]
    if ref.isdigit():
        index = int(ref) - 1
        if 0 <= index < len(retrieval.hits):
            return retrieval.hits[index]
    return None


PAPER_PROCESS_OBJECTIVE = "answer_paper_process_question"
ALIAS_GATE_DISABLED_OBJECTIVES = {EVIDENCE_QA_OBJECTIVE, PAPER_PROCESS_OBJECTIVE}
CROSS_DOCUMENT_COMPARE_RE = re.compile(
    r"(两篇|多篇|跨文档|跨论文|cross[-\s]?document|cross[-\s]?paper)",
    re.I,
)


def specific_enzyme_alias_context_from_request(
    enzyme_name: str,
    application_context: Optional[str],
    constraints: List[str],
    objective: str,
    retrieval: Optional[RetrievalResponse] = None,
) -> SpecificEnzymeAliasContext:
    if objective in ALIAS_GATE_DISABLED_OBJECTIVES:
        return SpecificEnzymeAliasContext(reason=f"objective:{objective}")
    if retrieval and retrieval.query_plan and retrieval.query_plan.document_scope:
        return SpecificEnzymeAliasContext(reason="document_scope")

    text = request_alias_text(enzyme_name, application_context, constraints)
    alias_keys = matched_enzyme_alias_keys(text)
    if len(extract_document_ids(text)) > 1:
        return SpecificEnzymeAliasContext(reason="multiple_documents")
    if CROSS_DOCUMENT_COMPARE_RE.search(text):
        return SpecificEnzymeAliasContext(reason="cross_document_comparison")
    if len(alias_keys) > 1:
        return SpecificEnzymeAliasContext(alias_keys=frozenset(alias_keys), reason="multiple_specific_aliases")

    if len(alias_keys) != 1:
        return SpecificEnzymeAliasContext(
            alias_keys=frozenset(alias_keys),
            reason="no_unique_specific_alias" if alias_keys else "no_specific_alias",
        )
    return SpecificEnzymeAliasContext(alias_keys=frozenset(alias_keys), enabled=True, reason="unique_specific_alias")


def request_alias_text(enzyme_name: str, application_context: Optional[str], constraints: List[str]) -> str:
    return " ".join(
        part
        for part in [
            enzyme_name or "",
            application_context or "",
            " ".join(constraints or []),
        ]
        if part
    ).strip()


def hit_supports_specific_enzyme_alias(hit: RetrievalHit, alias_keys: frozenset[str]) -> bool:
    if not alias_keys:
        return True
    if hit.requires_review or not hit.usable_for_ranking:
        return False
    return bool(alias_keys & matched_enzyme_alias_keys(hit_alias_match_text(hit)))


def refs_support_specific_enzyme_alias(
    item: Dict[str, Any],
    retrieval: RetrievalResponse,
    alias_keys: frozenset[str],
) -> bool:
    if not alias_keys:
        return True
    hits_by_id = {hit.source_id: hit for hit in retrieval.hits}
    hits_by_citation = {hit.citation: hit for hit in retrieval.hits if hit.citation}
    refs: List[RetrievalHit] = []
    for raw_ref in list(item.get("evidence_ids") or []) + list(item.get("citations") or []):
        hit = resolve_hit_ref(str(raw_ref).strip(), retrieval, hits_by_id, hits_by_citation)
        if hit is not None:
            refs.append(hit)
    return bool(refs) and any(hit_supports_specific_enzyme_alias(hit, alias_keys) for hit in refs)


def hit_alias_match_text(hit: RetrievalHit) -> str:
    return " ".join(
        [
            hit.text or "",
            hit.embedding_text or "",
            hit.source_chunk_text or "",
            hit.section or "",
            hit.document_id or "",
            hit.source_pdf or "",
            hit.citation or "",
            hit.record_type or "",
            hit.source_id or "",
            json.dumps(hit.extracted, ensure_ascii=False, sort_keys=True),
            json.dumps(hit.metrics, ensure_ascii=False, sort_keys=True),
        ]
    )
