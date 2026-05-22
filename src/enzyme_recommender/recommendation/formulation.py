from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from enzyme_recommender.generators import ChatMessage, GenerationRequest, GenerationResponse
from enzyme_recommender.rag.retrieval import RetrievalHit, RetrievalResponse
from enzyme_recommender.recommendation.enzyme import parse_json_object
from enzyme_recommender.runtime import RuntimeServices


class FormulationOptimizationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    enzyme_name: str
    user_formulation: Dict[str, Any]
    objective: str = "optimize_formulation"
    application_context: Optional[str] = None
    constraints: List[str] = Field(default_factory=list)
    top_k: Optional[int] = None

    @field_validator("enzyme_name")
    @classmethod
    def enzyme_name_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("enzyme_name must not be empty")
        return value.strip()

    @field_validator("user_formulation")
    @classmethod
    def formulation_must_not_be_empty(cls, value: Dict[str, Any]) -> Dict[str, Any]:
        if not value:
            raise ValueError("user_formulation must not be empty")
        return value


class FormulationChange(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    field_path: str
    current_value: Any = None
    recommended_value: Any = None
    rationale: str
    evidence_ids: List[str] = Field(default_factory=list)
    citations: List[str] = Field(default_factory=list)
    confidence: str = "low"


class FormulationOptimizationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    optimization_id: str
    created_at: str
    target_enzyme: str
    objective: str
    retrieval_query: str
    generator_provider: str
    generator_model: str
    changes: List[FormulationChange]
    evidence_hits: List[RetrievalHit]
    generation_content: str
    generation_json: Optional[Dict[str, Any]] = None
    limitations: List[str] = Field(default_factory=list)
    next_experiment_suggestions: List[Dict[str, Any]] = Field(default_factory=list)


class FormulationOptimizationService:
    def __init__(self, runtime: RuntimeServices) -> None:
        self.runtime = runtime

    def optimize_formulation(self, request: FormulationOptimizationRequest) -> FormulationOptimizationResponse:
        retrieval_query = build_formulation_retrieval_query(request)
        retrieval = self.runtime.retriever().retrieve(
            query=retrieval_query,
            top_k=request.top_k or self.runtime.config.retrieval.top_k,
            usable_only=self.runtime.config.retrieval.usable_only,
        )
        generation = self._generate_optimization(request, retrieval)
        generation_json = parse_json_object(generation.content)
        changes = build_changes_from_generation_or_evidence(generation_json, request, retrieval)
        return FormulationOptimizationResponse(
            optimization_id=make_optimization_id(request, retrieval),
            created_at=datetime.now(timezone.utc).isoformat(),
            target_enzyme=request.enzyme_name,
            objective=request.objective,
            retrieval_query=retrieval_query,
            generator_provider=generation.provider,
            generator_model=generation.model,
            changes=changes,
            evidence_hits=retrieval.hits,
            generation_content=generation.content,
            generation_json=generation_json,
            limitations=build_optimization_limitations(generation, retrieval, changes),
            next_experiment_suggestions=build_optimization_experiment_suggestions(changes, retrieval),
        )

    def _generate_optimization(
        self,
        request: FormulationOptimizationRequest,
        retrieval: RetrievalResponse,
    ) -> GenerationResponse:
        config = self.runtime.config
        provider_config = config.generator_providers[config.generator.provider]
        generator = self.runtime.generator()
        return generator.generate(
            GenerationRequest(
                messages=[
                    ChatMessage(role="system", content=SYSTEM_PROMPT),
                    ChatMessage(role="user", content=build_optimization_prompt(request, retrieval)),
                ],
                model=provider_config.model,
                temperature=config.generator.temperature,
                response_format="json_object",
                timeout_seconds=config.generator.timeout_seconds,
                max_retries=config.generator.max_retries,
            )
        )


SYSTEM_PROMPT = """你是一个面向生物酶固定化配方优化的 evidence-first 助手。
只能基于给定 evidence context 对用户配方提出字段级优化建议。不要声称找到全局最优；必须说明证据、适用边界和下一步实验。输出必须是 JSON object。"""


def build_formulation_retrieval_query(request: FormulationOptimizationRequest) -> str:
    formulation_text = json.dumps(request.user_formulation, ensure_ascii=False, sort_keys=True)
    parts = [
        request.enzyme_name,
        request.objective,
        request.application_context or "",
        " ".join(request.constraints),
        formulation_text,
        "immobilization formulation conditions enzyme loading carrier amount pH temperature time activity recovery yield reusability",
    ]
    return " ".join(part for part in parts if part).strip()


def build_optimization_prompt(request: FormulationOptimizationRequest, retrieval: RetrievalResponse) -> str:
    return "\n\n".join(
        [
            "任务：比较用户配方与 evidence context，输出字段级优化建议。",
            f"目标酶：{request.enzyme_name}",
            f"目标：{request.objective}",
            f"应用场景：{request.application_context or '未提供'}",
            f"用户约束：{request.constraints or '未提供'}",
            "用户配方 JSON:",
            json.dumps(request.user_formulation, ensure_ascii=False, sort_keys=True, indent=2),
            "Evidence context:",
            retrieval.context_text(max_chars_per_hit=900),
            "请输出 JSON object："
            '{"changes":[{"field_path":"","current_value":null,"recommended_value":null,'
            '"rationale":"","evidence_ids":[],"citations":[],"confidence":"low|medium|high"}],'
            '"limitations":[],"next_experiment_suggestions":[]}',
        ]
    )


def build_changes_from_generation_or_evidence(
    generation_json: Optional[Dict[str, Any]],
    request: FormulationOptimizationRequest,
    retrieval: RetrievalResponse,
) -> List[FormulationChange]:
    if generation_json and isinstance(generation_json.get("changes"), list):
        changes = []
        for raw_change in generation_json["changes"]:
            if not isinstance(raw_change, dict):
                continue
            try:
                changes.append(FormulationChange.model_validate(raw_change))
            except ValueError:
                continue
        if changes:
            return changes

    reference_items = collect_reference_items(retrieval)
    current_by_alias = flatten_with_aliases(request.user_formulation)
    changes: List[FormulationChange] = []
    seen_fields: set[str] = set()

    for item in reference_items:
        field_path = canonical_field_path(item.key)
        if field_path in seen_fields:
            continue
        current = current_by_alias.get(alias_key(item.key))
        if values_are_equivalent(current, item.value):
            continue
        changes.append(
            FormulationChange(
                field_path=field_path,
                current_value=current,
                recommended_value=item.value,
                rationale=(
                    f"Evidence reports {item.key}={value_label(item.value)} for a related "
                    "lipase immobilization setup; use it as a starting point and validate experimentally."
                ),
                evidence_ids=[item.hit.source_id],
                citations=[item.hit.citation] if item.hit.citation else [],
                confidence=item.hit.confidence or "medium",
            )
        )
        seen_fields.add(field_path)
        if len(changes) >= 6:
            break

    return changes


class ReferenceItem(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    key: str
    value: Any
    hit: RetrievalHit


CONDITION_KEYS = {
    "carrier",
    "carrier_variant",
    "immobilization_method",
    "enzyme_loading",
    "carrier_amount",
    "enzyme_to_carrier_ratio",
    "adsorption_time",
    "immobilization_time",
    "immobilization_temperature",
    "temperature",
    "pH",
    "ph",
    "buffer",
    "additives",
}


def collect_reference_items(retrieval: RetrievalResponse) -> List[ReferenceItem]:
    items: List[ReferenceItem] = []
    for hit in retrieval.hits:
        if hit.record_type not in {"formulation_condition", "immobilization_strategy", "table_comparison_row"}:
            continue
        for key, value in hit.extracted.items():
            if key not in CONDITION_KEYS or value is None or value == "" or value == []:
                continue
            items.append(ReferenceItem(key=key, value=value, hit=hit))
    return items


def flatten_with_aliases(payload: Dict[str, Any]) -> Dict[str, Any]:
    flattened: Dict[str, Any] = {}

    def walk(prefix: str, value: Any) -> None:
        if isinstance(value, dict):
            if prefix:
                flattened[alias_key(prefix)] = value
            for child_key, child_value in value.items():
                child_path = f"{prefix}.{child_key}" if prefix else str(child_key)
                walk(child_path, child_value)
            return
        flattened[alias_key(prefix)] = value

    walk("", payload)
    return flattened


def alias_key(path: str) -> str:
    key = path.lower().replace("-", "_")
    key = key.split(".")[-1]
    aliases = {
        "ph": "pH",
        "immobilization_temperature": "temperature",
        "adsorption_time": "time",
        "immobilization_time": "time",
        "enzyme_loading": "enzyme_loading",
        "loading": "enzyme_loading",
        "carrier_variant": "carrier",
        "support": "carrier",
        "method": "immobilization_method",
    }
    return aliases.get(key, key)


def canonical_field_path(key: str) -> str:
    canonical = {
        "carrier_variant": "carrier",
        "adsorption_time": "immobilization_conditions.time",
        "immobilization_time": "immobilization_conditions.time",
        "immobilization_temperature": "immobilization_conditions.temperature",
        "temperature": "immobilization_conditions.temperature",
        "pH": "buffer.pH",
        "ph": "buffer.pH",
        "enzyme_loading": "enzyme.amount",
    }
    return canonical.get(key, key)


def values_are_equivalent(current: Any, reference: Any) -> bool:
    if current is None:
        return False
    if isinstance(current, (int, float)) and isinstance(reference, (int, float)):
        return abs(float(current) - float(reference)) < 1e-9
    return normalize_for_compare(current) == normalize_for_compare(reference)


def normalize_for_compare(value: Any) -> str:
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True).lower()
    return str(value).strip().lower()


def value_label(value: Any) -> str:
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def build_optimization_limitations(
    generation: GenerationResponse,
    retrieval: RetrievalResponse,
    changes: List[FormulationChange],
) -> List[str]:
    limitations = []
    if generation.provider == "mock":
        limitations.append("mock generator only validates pipeline wiring; final optimization wording requires SiliconFlow/DeepSeek.")
    if not retrieval.hits:
        limitations.append("no usable evidence was retrieved")
    if not changes:
        limitations.append("no field-level changes were generated from the current evidence")
    if any(hit.requires_review for hit in retrieval.hits):
        limitations.append("some retrieved evidence requires review and should not be used for ranking")
    limitations.append("recommendations are evidence-based starting points, not a global optimum without DOE validation")
    return limitations


def build_optimization_experiment_suggestions(
    changes: List[FormulationChange],
    retrieval: RetrievalResponse,
) -> List[Dict[str, Any]]:
    variables = [change.field_path for change in changes[:4]]
    if not variables:
        variables = ["enzyme.amount", "carrier", "buffer.pH", "immobilization_conditions.temperature"]
    return [
        {
            "variables": variables,
            "metric": "activity recovery, immobilization yield, product yield, residual activity after reuse",
            "evidence_basis": [hit.citation for hit in retrieval.hits[:3] if hit.citation],
        }
    ]


def make_optimization_id(request: FormulationOptimizationRequest, retrieval: RetrievalResponse) -> str:
    seed = "|".join(
        [
            request.enzyme_name,
            request.objective,
            json.dumps(request.user_formulation, ensure_ascii=False, sort_keys=True),
            ",".join(hit.source_id for hit in retrieval.hits[:5]),
        ]
    )
    digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()
    return f"opt_{digest[:12]}"
