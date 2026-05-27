from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

from pydantic import BaseModel, ConfigDict, Field, field_validator

from enzyme_recommender.generators import ChatMessage, GenerationRequest, GenerationResponse
from enzyme_recommender.rag.enzyme_aliases import matched_enzyme_alias_terms
from enzyme_recommender.rag.retrieval import RetrievalHit, RetrievalResponse
from enzyme_recommender.recommendation.enzyme import (
    SpecificEnzymeAliasContext,
    hit_supports_specific_enzyme_alias,
    parse_json_object,
    refs_support_specific_enzyme_alias,
    resolve_evidence_refs,
    specific_enzyme_alias_context_from_request,
)
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
        retrieval = self.retrieve_evidence(request)
        generation = self._generate_optimization(request, retrieval)
        return self.build_response(request, retrieval, generation)

    def retrieve_evidence(self, request: FormulationOptimizationRequest) -> RetrievalResponse:
        retrieval_query = build_formulation_retrieval_query(request)
        requested_top_k = request.top_k or self.runtime.config.retrieval.top_k
        retrieval_top_k = max(
            requested_top_k * self.runtime.config.retrieval.formulation_candidate_multiplier,
            self.runtime.config.retrieval.formulation_candidate_min,
        )
        retrieval = self.runtime.retriever().retrieve(
            query=retrieval_query,
            top_k=retrieval_top_k,
            usable_only=self.runtime.config.retrieval.usable_only,
        )
        document_scoped = bool(retrieval.query_plan and retrieval.query_plan.document_scope)
        prioritized_hits = prioritize_formulation_hits(
            retrieval.hits,
            query=retrieval_query,
            document_scoped=document_scoped,
        )
        return retrieval.model_copy(update={"top_k": requested_top_k, "hits": prioritized_hits[:requested_top_k]})

    def build_generation_request(
        self,
        request: FormulationOptimizationRequest,
        retrieval: RetrievalResponse,
    ) -> GenerationRequest:
        config = self.runtime.config
        provider_config = config.generator_providers[config.generator.provider]
        return GenerationRequest(
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

    def build_stream_generation_request(
        self,
        request: FormulationOptimizationRequest,
        retrieval: RetrievalResponse,
    ) -> GenerationRequest:
        base_request = self.build_generation_request(request, retrieval)
        return base_request.model_copy(
            update={
                "messages": [
                    ChatMessage(role="system", content=STREAM_SYSTEM_PROMPT),
                    ChatMessage(role="user", content=build_stream_optimization_prompt(request, retrieval)),
                ],
                "response_format": "text",
                "max_retries": 0,
            }
        )

    def build_response(
        self,
        request: FormulationOptimizationRequest,
        retrieval: RetrievalResponse,
        generation: GenerationResponse,
    ) -> FormulationOptimizationResponse:
        generation_json = parse_json_object(generation.content)
        alias_context = specific_enzyme_alias_context_from_request(
            enzyme_name=request.enzyme_name,
            application_context=request.application_context,
            constraints=request.constraints,
            objective=request.objective,
            retrieval=retrieval,
        )
        changes = build_changes_from_generation_or_evidence(generation_json, request, retrieval, alias_context)
        return FormulationOptimizationResponse(
            optimization_id=make_optimization_id(request, retrieval),
            created_at=datetime.now(timezone.utc).isoformat(),
            target_enzyme=request.enzyme_name,
            objective=request.objective,
            retrieval_query=build_formulation_retrieval_query(request),
            generator_provider=generation.provider,
            generator_model=generation.model,
            changes=changes,
            evidence_hits=retrieval.hits,
            generation_content=generation.content,
            generation_json=generation_json,
            limitations=build_optimization_limitations(generation, retrieval, changes, generation_json, alias_context),
            next_experiment_suggestions=build_optimization_experiment_suggestions(
                changes,
                retrieval,
                generation_json,
                alias_context,
            ),
        )

    def _generate_optimization(
        self,
        request: FormulationOptimizationRequest,
        retrieval: RetrievalResponse,
    ) -> GenerationResponse:
        generator = self.runtime.generator()
        return generator.generate(self.build_generation_request(request, retrieval))


SYSTEM_PROMPT = """你是一个面向生物酶固定化配方优化的 evidence-first 助手。
只能基于给定 evidence context 对用户配方提出字段级优化建议。不要声称找到全局最优；必须说明证据、适用边界和下一步实验。输出必须是 JSON object。"""


STREAM_SYSTEM_PROMPT = """你是一个面向生物酶固定化配方优化的 evidence-first 助手。
优先快速输出可读建议，不输出 JSON。只能基于给定 evidence context；每条字段级建议必须带形如 [1]、[2] 的 reference index。"""


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


def build_stream_optimization_prompt(request: FormulationOptimizationRequest, retrieval: RetrievalResponse) -> str:
    return "\n\n".join(
        [
            "任务：快速比较用户配方与 evidence context，输出前端 live stream 首答。",
            f"目标酶：{request.enzyme_name}",
            f"目标：{request.objective}",
            f"应用场景：{request.application_context or '未提供'}",
            f"用户约束：{request.constraints or '未提供'}",
            "用户配方 JSON:",
            json.dumps(request.user_formulation, ensure_ascii=False, sort_keys=True, indent=2),
            "Evidence context:",
            retrieval.context_text(max_chars_per_hit=600),
            "输出要求：",
            "- 先给 1 句总体判断，再给 3-6 条字段级改动建议。",
            "- 每条建议写清 current -> recommended、rationale，并只使用 [1]、[2] 这类 reference index 引用，不要写裸 citation。",
            "- 明确哪些建议只是 starting point，需要 DOE 或对照实验验证。",
            "- 不输出 JSON，不要引入 evidence context 之外的新事实。",
        ]
    )


def build_changes_from_generation_or_evidence(
    generation_json: Optional[Dict[str, Any]],
    request: FormulationOptimizationRequest,
    retrieval: RetrievalResponse,
    alias_context: Optional[SpecificEnzymeAliasContext] = None,
) -> List[FormulationChange]:
    specific_alias_keys = alias_context.alias_keys if alias_context and alias_context.enabled else frozenset()
    if generation_json and isinstance(generation_json.get("changes"), list):
        changes = []
        for raw_change in generation_json["changes"]:
            if not isinstance(raw_change, dict):
                continue
            raw_change = sanitize_generation_change(raw_change, retrieval)
            if not raw_change["evidence_ids"] and not raw_change["citations"]:
                continue
            if not refs_support_specific_enzyme_alias(raw_change, retrieval, specific_alias_keys):
                continue
            try:
                changes.append(FormulationChange.model_validate(raw_change))
            except ValueError:
                continue
        if changes:
            return changes

    reference_items = collect_reference_items(retrieval, specific_alias_keys=specific_alias_keys)
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


def sanitize_generation_change(change: Dict[str, Any], retrieval: RetrievalResponse) -> Dict[str, Any]:
    sanitized = dict(change)
    sanitized["evidence_ids"], sanitized["citations"] = resolve_evidence_refs(
        raw_ids=sanitized.get("evidence_ids"),
        raw_citations=sanitized.get("citations"),
        retrieval=retrieval,
    )
    if sanitized.get("confidence") not in {"low", "medium", "high"}:
        sanitized["confidence"] = "medium"
    return sanitized


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


def collect_reference_items(
    retrieval: RetrievalResponse,
    specific_alias_keys: Optional[frozenset[str]] = None,
) -> List[ReferenceItem]:
    items: List[ReferenceItem] = []
    for hit in retrieval.hits:
        if not hit_supports_specific_enzyme_alias(hit, specific_alias_keys or frozenset()):
            continue
        if hit.record_type not in {"formulation_condition", "immobilization_strategy", "table_comparison_row"}:
            continue
        for key, value in hit.extracted.items():
            if key not in CONDITION_KEYS or value is None or value == "" or value == []:
                continue
            items.append(ReferenceItem(key=key, value=value, hit=hit))
    return items


def prioritize_formulation_hits(
    hits: List[RetrievalHit],
    query: str = "",
    document_scoped: bool = False,
) -> List[RetrievalHit]:
    def key(hit: RetrievalHit) -> tuple[int, int, float, int]:
        if hit.record_type == "formulation_condition":
            record_rank = 0
        elif hit.record_type == "immobilization_strategy":
            record_rank = 1
        elif hit.record_type == "table_comparison_row":
            record_rank = 2
        else:
            record_rank = 3
        has_condition_fields = int(not any(field in hit.extracted for field in CONDITION_KEYS))
        page = hit.page_start if hit.page_start is not None else 10_000
        score = hit.rerank_score if hit.rerank_score is not None else hit.score
        if document_scoped:
            return (record_rank, has_condition_fields, float(page), int(-float(score) * 1_000_000))
        return (record_rank, has_condition_fields, -formulation_query_match_score(query, hit, float(score)), page)

    return sorted(hits, key=key)


def formulation_query_match_score(query: str, hit: RetrievalHit, base_score: float) -> float:
    text = formulation_hit_text(hit)
    query_terms = formulation_match_terms(query)
    text_terms = formulation_match_terms(text)
    bonus = 0.0
    entity_overlap = query_terms["entities"] & text_terms["entities"]
    condition_overlap = query_terms["conditions"] & text_terms["conditions"]
    protein_overlap = query_terms["proteins"] & text_terms["proteins"]
    material_overlap = query_terms["materials"] & text_terms["materials"]
    numeric_condition_overlap = query_terms["numeric_conditions"] & text_terms["numeric_conditions"]
    numeric_overlap = query_terms["numeric"] & text_terms["numeric"]
    construct_overlap = query_terms["constructs"] & text_terms["constructs"]
    bonus += min(0.18, 0.06 * len(entity_overlap))
    bonus += min(0.12, 0.035 * len(numeric_overlap))
    bonus += min(0.28, 0.14 * len(numeric_condition_overlap))
    bonus += min(0.18, 0.045 * len(condition_overlap))
    bonus += min(0.24, 0.12 * len(protein_overlap))
    bonus += min(0.18, 0.06 * len(material_overlap))
    bonus += min(0.48, 0.32 * len(construct_overlap))
    extracted = hit.extracted if isinstance(hit.extracted, dict) else {}
    if "loading" in query_terms["conditions"] and extracted.get("enzyme_loading") is not None:
        bonus += 0.18
    if "time" in query_terms["conditions"] and (
        extracted.get("adsorption_time") is not None or extracted.get("immobilization_time") is not None
    ):
        bonus += 0.18
    return base_score + bonus


FORMULATION_HYPHEN_TRANSLATION = str.maketrans(
    {
        "\u2010": "-",
        "\u2011": "-",
        "\u2012": "-",
        "\u2013": "-",
        "\u2014": "-",
        "\u2015": "-",
        "\u2212": "-",
    }
)
FORMULATION_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9@+\-/\.]{1,}|[0-9]+(?:\.[0-9]+)?%?", re.I)
FORMULATION_ENTITY_RE = re.compile(
    r"\b(?:[A-Za-z]{1,8}\s*@\s*)?[A-Za-z0-9]+(?:[-/][A-Za-z0-9]+)+(?:[-/][A-Za-z0-9]+)*\b",
    re.I,
)
FORMULATION_MATERIAL_RE = re.compile(
    r"\b(?:"
    r"zif-?\d+|uio-?\d+(?:-nh2)?|mil-?\d+[a-z]?|mof-?\d+|bio-mof|hkust-?\d+|"
    r"cu-btc|zn-btc|fe3o4|mcm-?\d+|nkmof-?\d+(?:-[a-z0-9]+)?|nu-?\d+|"
    r"mofs?|mnp|magnetic|sds|peg|carrier|support"
    r")\b",
    re.I,
)
FORMULATION_CONDITION_VALUE_PATTERNS = [
    ("ph", re.compile(r"\bph\s*(?:value\s*)?(?:of\s*)?[:=]?\s*(\d+(?:\.\d+)?)", re.I)),
    ("temperature", re.compile(r"\b(\d+(?:\.\d+)?)\s*(?:degc|°c|c)\b", re.I)),
    ("time", re.compile(r"\b(\d+(?:\.\d+)?)\s*(?:min|mins|minute|minutes|h|hr|hrs|hour|hours)\b", re.I)),
    ("loading", re.compile(r"\b(\d+(?:\.\d+)?)\s*(?:mg/g|mg\s*/\s*g|mg|g)\b", re.I)),
]
FORMULATION_CONDITION_ALIASES = {
    "loading": "loading",
    "enzyme_loading": "loading",
    "carrier_amount": "carrier_amount",
    "amount": "carrier_amount",
    "dosage": "carrier_amount",
    "ph": "ph",
    "temperature": "temperature",
    "time": "time",
    "adsorption_time": "time",
    "immobilization_time": "time",
    "buffer": "buffer",
    "concentration": "concentration",
    "ratio": "ratio",
    "yield": "yield",
    "activity": "activity",
    "recovery": "recovery",
    "reuse": "reuse",
    "reusability": "reuse",
    "cycles": "reuse",
    "cycle": "reuse",
    "stability": "stability",
    "conversion": "conversion",
    "条件": "condition",
    "配方": "condition",
    "优化": "condition",
    "制备": "condition",
    "温度": "temperature",
    "时间": "time",
    "浓度": "concentration",
    "比例": "ratio",
    "投料": "carrier_amount",
    "加量": "carrier_amount",
    "酶量": "loading",
    "活性": "activity",
    "回收率": "recovery",
    "产率": "yield",
    "转化率": "conversion",
    "复用": "reuse",
    "循环": "reuse",
    "稳定性": "stability",
}
FORMULATION_GENERIC_TOKENS = {
    "lipase",
    "enzyme",
    "immobilization",
    "immobilized",
    "formulation",
    "condition",
    "conditions",
    "carrier",
    "support",
    "method",
    "activity",
    "固定化",
    "脂肪酶",
    "载体",
    "材料",
}
FORMULATION_PROTEIN_ALIASES = {
    "bcl": {"bcl", "burkholderia", "cepacia"},
    "calb": {"calb", "cal-b", "candida", "antarctica"},
    "crl": {"crl", "rugosa"},
    "pfl": {"pfl", "pseudomonas", "fluorescens"},
    "ppl": {"ppl", "porcine", "pancreatic"},
    "rml": {"rml", "rhizomucor", "miehei"},
    "tll": {"tll", "thermomyces", "lanuginosus"},
    "lipase": {"lipase"},
    "enzyme": {"enzyme"},
}


def formulation_hit_text(hit: RetrievalHit) -> str:
    return " ".join(
        [
            hit.text or "",
            hit.embedding_text or "",
            json.dumps(hit.extracted, ensure_ascii=False, sort_keys=True),
            json.dumps(hit.metrics, ensure_ascii=False, sort_keys=True),
        ]
    )


def formulation_match_terms(text: str) -> Dict[str, set[str]]:
    normalized = normalize_formulation_text(text)
    raw_tokens = {canonical_formulation_token(match.group(0)) for match in FORMULATION_TOKEN_RE.finditer(normalized)}
    raw_tokens = {token for token in raw_tokens if token}
    tokens = {token for token in raw_tokens if token not in FORMULATION_GENERIC_TOKENS}
    entities = {
        canonical_formulation_token(match.group(0))
        for match in FORMULATION_ENTITY_RE.finditer(normalized)
        if canonical_formulation_token(match.group(0))
    }
    materials = formulation_material_terms(normalized, tokens | entities)
    entities.update(
        token
        for token in tokens
        if (
            "@" in token
            or "-" in token
            or "/" in token
            or any(marker in token for marker in ("zif", "uio", "mil", "mof", "hkust", "btc", "fe3o4", "mcm", "pnipam"))
        )
    )
    numeric = {token.rstrip("%") for token in tokens if re.fullmatch(r"\d+(?:\.\d+)?%?", token)}
    conditions = {FORMULATION_CONDITION_ALIASES[token] for token in tokens if token in FORMULATION_CONDITION_ALIASES}
    conditions.update(
        alias for raw, alias in FORMULATION_CONDITION_ALIASES.items() if any(ord(char) > 127 for char in raw) and raw in normalized
    )
    proteins = formulation_protein_terms(raw_tokens | entities)
    constructs = formulation_construct_terms(normalized, proteins, materials, tokens | entities)
    numeric_conditions = formulation_numeric_condition_terms(normalized)
    return {
        "entities": entities,
        "numeric": numeric,
        "numeric_conditions": numeric_conditions,
        "conditions": conditions,
        "materials": materials,
        "proteins": proteins,
        "constructs": constructs,
        "tokens": tokens,
    }


def formulation_protein_terms(tokens: Sequence[str]) -> set[str]:
    proteins: set[str] = set()
    for protein, aliases in FORMULATION_PROTEIN_ALIASES.items():
        if (
            protein in tokens
            or len(set(tokens) & aliases) >= 2
            or any(token.startswith(f"{protein}-") or token.startswith(f"{protein}@") for token in tokens)
        ):
            proteins.add(protein)
    return proteins


def formulation_material_terms(normalized: str, tokens: Sequence[str]) -> set[str]:
    materials = {canonical_material_token(match.group(0)) for match in FORMULATION_MATERIAL_RE.finditer(normalized)}
    for token in tokens:
        for match in FORMULATION_MATERIAL_RE.finditer(token):
            material = canonical_material_token(match.group(0))
            if material:
                materials.add(material)
    return {material for material in materials if material}


def formulation_construct_terms(
    normalized: str,
    proteins: set[str],
    materials: set[str],
    tokens: Sequence[str],
) -> set[str]:
    constructs: set[str] = set()
    token_text = " ".join(tokens)
    for protein in proteins:
        for material in materials:
            if material in {"carrier", "support"} and protein not in {"enzyme", "lipase"}:
                continue
            constructs.add(f"{protein}|{material}")

    # Preserve modifier-aware forms when the query or evidence names a concrete complex.
    modifier_tokens = {
        modifier
        for token in tokens
        for modifier in {"sds", "peg", "mnp", "magnetic"}
        if canonical_formulation_token(token) == modifier
        or canonical_formulation_token(token).startswith(f"{modifier}-")
        or f"-{modifier}" in canonical_formulation_token(token)
        or f"@{modifier}" in canonical_formulation_token(token)
    }
    for protein in proteins:
        for material in materials:
            for modifier in modifier_tokens:
                if modifier == material:
                    continue
                if construct_components_are_near(normalized, protein, modifier, material) or construct_components_are_near(
                    token_text, protein, modifier, material
                ):
                    constructs.add(f"{protein}|{modifier}|{material}")
    return constructs


def construct_components_are_near(text: str, protein: str, modifier: str, material: str) -> bool:
    pattern = re.compile(
        rf"\b{re.escape(protein)}\b[\w\s@+\-/]{{0,36}}\b{re.escape(modifier)}\b[\w\s@+\-/]{{0,36}}\b{re.escape(material)}\b"
        rf"|\b{re.escape(protein)}\b[\w\s@+\-/]{{0,36}}\b{re.escape(material)}\b[\w\s@+\-/]{{0,36}}\b{re.escape(modifier)}\b",
        re.I,
    )
    return bool(pattern.search(text))


def formulation_numeric_condition_terms(normalized: str) -> set[str]:
    terms: set[str] = set()
    for label, pattern in FORMULATION_CONDITION_VALUE_PATTERNS:
        for match in pattern.finditer(normalized):
            value = canonical_formulation_token(match.group(1))
            if value:
                terms.add(f"{label}:{value.rstrip('%')}")
    return terms


def canonical_material_token(token: str) -> str:
    value = canonical_formulation_token(token)
    replacements = {
        "zif8": "zif-8",
        "uio66": "uio-66",
        "uio-66-nh2": "uio-66-nh2",
        "mof": "mof",
        "mofs": "mof",
        "mnp": "mnp",
    }
    return replacements.get(value, value)


def normalize_formulation_text(text: str) -> str:
    normalized = (text or "").translate(FORMULATION_HYPHEN_TRANSLATION).lower()
    alias_terms = matched_enzyme_alias_terms(text or "")
    if alias_terms:
        normalized = " ".join([normalized, *(term.lower() for term in alias_terms)])
    replacements = {
        "脂肪酶": " lipase ",
        "生物柴油": " biodiesel ",
        "大豆油": " soybean oil ",
        "乙醇": " ethanol ",
        "甲醇": " methanol ",
        "转酯": " transesterification ",
        "酯化": " esterification ",
        "重复使用": " reuse reusability cycles ",
        "重复用": " reuse reusability cycles ",
        "复用": " reuse reusability cycles ",
        "循环": " cycles ",
        "稳定性": " stability ",
        "更稳": " stability retained activity ",
    }
    for raw, replacement in replacements.items():
        normalized = normalized.replace(raw, replacement)
    normalized = normalized.replace("°c", " c ")
    normalized = re.sub(r"\blipa\s+se\s*@", "lipase@", normalized, flags=re.I)
    return normalized


def canonical_formulation_token(token: str) -> str:
    value = (token or "").lower().strip("-_.,;:()[]{}\"'")
    value = re.sub(r"\s*@\s*", "@", value)
    value = value.replace("zif8", "zif-8").replace("uio66", "uio-66")
    value = value.replace("bcl@zif-8", "bcl-zif-8")
    if re.fullmatch(r"\d+\.0+", value):
        value = value.split(".", 1)[0]
    return value


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
    generation_json: Optional[Dict[str, Any]] = None,
    alias_context: Optional[SpecificEnzymeAliasContext] = None,
) -> List[str]:
    limitations = []
    specific_alias_keys = alias_context.alias_keys if alias_context and alias_context.enabled else frozenset()
    if generation_json:
        limitations.extend(string_items(generation_json.get("limitations")))
    if generation.provider == "mock":
        limitations.append("mock generator only validates pipeline wiring; final optimization wording requires SiliconFlow/DeepSeek.")
    if not retrieval.hits:
        limitations.append("no usable evidence was retrieved")
    elif specific_alias_keys and not any(hit_supports_specific_enzyme_alias(hit, specific_alias_keys) for hit in retrieval.hits):
        limitations.append("no usable evidence for the requested enzyme alias was retrieved")
    if not changes:
        limitations.append("no field-level changes were generated from the current evidence")
    if any(hit.requires_review for hit in retrieval.hits):
        limitations.append("some retrieved evidence requires review and should not be used for ranking")
    limitations.append("recommendations are evidence-based starting points, not a global optimum without DOE validation")
    return dedupe_strings(limitations)


def build_optimization_experiment_suggestions(
    changes: List[FormulationChange],
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
