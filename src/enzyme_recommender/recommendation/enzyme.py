from __future__ import annotations

import json
import hashlib
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from enzyme_recommender.generators import ChatMessage, GenerationRequest, GenerationResponse
from enzyme_recommender.rag.retrieval import RetrievalHit, RetrievalResponse
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


class RecommendationService:
    def __init__(self, runtime: RuntimeServices) -> None:
        self.runtime = runtime

    def recommend_by_enzyme(self, request: EnzymeRecommendationRequest) -> EnzymeRecommendationResponse:
        retrieval = self.retrieve_evidence(request)
        generation = self._generate_recommendation(request, retrieval)
        return self.build_response(request, retrieval, generation)

    def retrieve_evidence(self, request: EnzymeRecommendationRequest) -> RetrievalResponse:
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
        generation_json = parse_json_object(generation.content)
        candidates = build_candidates_from_generation_or_evidence(generation_json, retrieval)
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
            limitations=build_limitations(generation, retrieval, generation_json),
            next_experiment_suggestions=build_next_experiment_suggestions(retrieval, generation_json),
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
    parts = [
        request.enzyme_name,
        "immobilization carrier support method conditions activity recovery yield reusability stability",
        request.objective,
        request.application_context or "",
        " ".join(request.constraints),
    ]
    return " ".join(part for part in parts if part).strip()


def build_generation_prompt(request: EnzymeRecommendationRequest, retrieval: RetrievalResponse) -> str:
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


def build_candidates_from_generation_or_evidence(
    generation_json: Optional[Dict[str, Any]],
    retrieval: RetrievalResponse,
) -> List[RecommendedCandidate]:
    if generation_json and isinstance(generation_json.get("candidates"), list):
        candidates = []
        for index, raw_candidate in enumerate(generation_json["candidates"], start=1):
            if not isinstance(raw_candidate, dict):
                continue
            sanitized = _sanitize_candidate(raw_candidate, retrieval)
            if not sanitized["evidence_ids"] and not sanitized["citations"]:
                continue
            try:
                candidates.append(RecommendedCandidate.model_validate(sanitized))
            except ValueError:
                continue
        if candidates:
            return candidates

    evidence_candidates = []
    formulation_conditions = first_formulation_conditions(retrieval)
    for hit in retrieval.hits:
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
    if not evidence_candidates and retrieval.hits:
        top = retrieval.hits[0]
        evidence_candidates.append(
            RecommendedCandidate(
                rank=1,
                strategy_summary=top.text[:300] if top.text else "retrieved evidence",
                carrier=None,
                immobilization_method=None,
                recommended_conditions=first_formulation_conditions(retrieval),
                expected_benefits=benefits_from_hit(top),
                risks=[],
                evidence_ids=[top.source_id],
                citations=[top.citation] if top.citation else [],
                confidence=top.confidence or "low",
            )
        )

    return evidence_candidates


def first_formulation_conditions(retrieval: RetrievalResponse) -> Dict[str, Any]:
    for hit in retrieval.hits:
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
) -> List[str]:
    limitations = []
    if generation_json:
        limitations.extend(string_items(generation_json.get("limitations")))
    if generation.provider == "mock":
        limitations.append("mock generator only validates pipeline wiring; final wording requires SiliconFlow/DeepSeek.")
    if not retrieval.hits:
        limitations.append("no usable evidence was retrieved")
    if any(hit.requires_review for hit in retrieval.hits):
        limitations.append("some retrieved evidence requires review and should not be used for ranking")
    return dedupe_strings(limitations)


def build_next_experiment_suggestions(
    retrieval: RetrievalResponse,
    generation_json: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
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
