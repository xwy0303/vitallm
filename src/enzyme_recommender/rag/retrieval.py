from __future__ import annotations

import json
import re
import math
from typing import Any, Dict, List, Literal, Optional, Sequence, Tuple, Union

from pydantic import BaseModel, ConfigDict, Field

from enzyme_recommender.rag.embedding import HashEmbeddingConfig, HashEmbeddingModel, SentenceEmbeddingModel
from enzyme_recommender.rag.enzyme_aliases import (
    expand_query_for_retrieval,
    matched_enzyme_alias_keys,
    matched_enzyme_alias_terms,
)
from enzyme_recommender.rag.qdrant import QdrantConfig, QdrantRestClient


PointType = Literal["rag_chunk", "table_record", "evidence_record"]
RecordType = Literal[
    "enzyme_identity",
    "immobilization_strategy",
    "formulation_condition",
    "performance_metric",
    "table_comparison_row",
]
TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9\-]{1,}|[0-9]+(?:\.[0-9]+)?%?")
DOCUMENT_ID_RE = re.compile(
    r"(?<![A-Za-z0-9])([ABCabc])0*(\d{1,3})(?:\s*\.?\s*(pdf))?(?![A-Za-z0-9])",
    re.I,
)
EXPLICIT_DOCUMENT_ID_RE = re.compile(
    r"\b(?:document_id|doc_id|source_pdf)\s*:\s*([ABCabc])0*(\d{1,3})(?:\s*\.?\s*pdf)?\b",
    re.I,
)
AT_CONSTRUCT_RE = re.compile(r"\b[A-Za-z][A-Za-z0-9\-]*(?:\s*@\s*[A-Za-z][A-Za-z0-9\-]*)+")
MATERIAL_RE = re.compile(
    r"\b(?:ZIF-8|ZIF-67|UiO-66|MIL-88A|MIL-101|MIL-100|MOF-5|HKUST-1|Cu-BTC|Zn-BTC|"
    r"NKMOF-101(?:-[A-Za-z0-9]+)?|MCM-41|MOF-199|NU-1000|"
    r"Li-MOF|Fe3O4|magnetic|hydroxyapatite|glycyrrhizin|PEI)\b",
    re.I,
)
CONDITION_VALUE_RE = re.compile(r"\b(?:pH\s*\d|\d+(?:\.\d+)?\s*(?:mg|mM|mmol|mol/L|mL|min|h|hours?|°C|C)\b)", re.I)
CONDITION_VALUE_PATTERNS = [
    ("ph", re.compile(r"\bph\s*(?:value\s*)?(?:of\s*)?[:=]?\s*(\d+(?:\.\d+)?)", re.I)),
    ("temperature", re.compile(r"\b(\d+(?:\.\d+)?)\s*(?:°c|degc|c)\b", re.I)),
    ("time", re.compile(r"\b(\d+(?:\.\d+)?)\s*(?:min|mins|minute|minutes|h|hr|hrs|hour|hours)\b", re.I)),
]
TABLE_QUERY_TERMS = {
    "table",
    "row",
    "yield",
    "activity",
    "recovery",
    "reusability",
    "reuse",
    "cycle",
    "cycles",
    "condition",
    "conditions",
    "temperature",
    "ph",
    "time",
    "substrate",
    "biodiesel",
    "comparison",
    "compare",
    "versus",
}
ENZYME_QUERY_TERMS = {
    "enzyme",
    "lipase",
    "calb",
    "cal-b",
    "bcl",
    "crl",
    "pfl",
    "ppl",
    "rml",
    "tll",
    "ays",
    "novozym",
}
STRATEGY_QUERY_TERMS = {
    "carrier",
    "support",
    "method",
    "immobilization",
    "immobilized",
    "encapsulation",
    "adsorption",
    "covalent",
    "crosslinking",
    "cross-linked",
    "mof",
    "zif-8",
    "zif8",
    "uio-66",
    "uio66",
    "pnipam",
    "thermo-switchable",
    "thermoswitchable",
    "size-selective",
}
MECHANISTIC_STRATEGY_MARKERS = {
    "thermo-switchable",
    "thermoswitchable",
    "blocked pores",
    "open pores",
    "size-selective",
    "pnipam",
    "mechanism",
    "selectivity",
}
CONDITION_QUERY_TERMS = {
    "condition",
    "conditions",
    "formulation",
    "loading",
    "ph",
    "temperature",
    "time",
    "buffer",
    "dosage",
    "concentration",
    "ratio",
    "amount",
    "min",
    "hour",
    "hours",
}
PERFORMANCE_QUERY_TERMS = {
    "yield",
    "activity",
    "recovery",
    "reusability",
    "reuse",
    "cycle",
    "cycles",
    "conversion",
    "stability",
    "residual",
    "retained",
}
APPLICATION_QUERY_TERMS = {
    "biodiesel",
    "transesterification",
    "esterification",
    "epoxidation",
    "furfural",
    "furfuryl",
    "substrate",
    "soybean",
    "oil",
    "pinene",
}
EVIDENCE_QUERY_TERMS = {
    *ENZYME_QUERY_TERMS,
    *STRATEGY_QUERY_TERMS,
    *CONDITION_QUERY_TERMS,
    *PERFORMANCE_QUERY_TERMS,
    *APPLICATION_QUERY_TERMS,
}
BAD_QUALITY_FLAGS = {
    "unrecoverable_page_placeholder",
    "placeholder_page_overlap",
    "bad_table_structure",
    "table_parse_empty",
    "table_header_suspect",
    "table_too_sparse",
    "table_ragged_rows",
    "rotated_or_wide_table_suspected",
    "suspicious_percent_gt_300",
    "suspicious_table_yield_gt_100",
}
LEXICAL_STOPWORDS = {
    "about",
    "after",
    "and",
    "are",
    "best",
    "for",
    "from",
    "high",
    "higher",
    "into",
    "led",
    "low",
    "of",
    "on",
    "onto",
    "or",
    "over",
    "should",
    "study",
    "than",
    "the",
    "this",
    "to",
    "using",
    "with",
}
NUMBER_WORDS = {
    "zero": "0",
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
    "ten": "10",
    "eleven": "11",
    "twelve": "12",
    "thirteen": "13",
    "fourteen": "14",
    "fifteen": "15",
    "sixteen": "16",
    "seventeen": "17",
    "eighteen": "18",
    "nineteen": "19",
    "twenty": "20",
    "half-hour": "30",
    "half": "0.5",
}
UNIT_TOKENS = {
    "c",
    "cm",
    "g",
    "h",
    "hr",
    "hrs",
    "hour",
    "hours",
    "khz",
    "m",
    "mg",
    "min",
    "ml",
    "mm",
    "mmol",
    "mol",
    "ph",
    "w",
}
DOMAIN_QUERY_TERMS = EVIDENCE_QUERY_TERMS | {
    "cal-b",
    "calb",
    "crl",
    "fame",
    "hkust-1",
    "lip",
    "mcm-41",
    "mof-199",
    "mof",
    "mofs",
    "mnp",
    "nanocomposite",
    "nk-mof",
    "nkmof-101",
    "nu-1000",
    "pnpb",
    "pnipam",
    "uio-66-nh2",
}
COMMON_MATERIAL_TOKENS = {
    "mof",
    "mofs",
    "zif-8",
    "zif8",
}
BROAD_DOMAIN_TOKENS = {
    "activity",
    "carrier",
    "enzyme",
    "hexane",
    "immobilization",
    "immobilized",
    "lipase",
    "method",
    "support",
}
CHINESE_TABLE_QUERY_TERMS = {"表格", "表", "对比", "比较", "哪一行"}
CHINESE_STRATEGY_QUERY_TERMS = {
    "固定化",
    "固定化剂",
    "载体",
    "材料",
    "包埋",
    "吸附",
    "共价",
    "交联",
    "策略",
}
CHINESE_CONDITION_QUERY_TERMS = {
    "条件",
    "配方",
    "优化",
    "制备",
    "温度",
    "时间",
    "浓度",
    "比例",
    "投料",
    "加量",
    "酶量",
}
CHINESE_PERFORMANCE_QUERY_TERMS = {
    "产率",
    "活性",
    "回收率",
    "重复使用",
    "重复用",
    "复用",
    "循环",
    "稳定性",
    "稳定",
    "更稳",
    "越高越好",
    "数据",
    "残余活性",
    "转化率",
}
CHINESE_ENZYME_QUERY_TERMS = {
    "脂肪酶",
    "伯克霍尔德菌",
    "南极假丝酵母",
    "皱褶假丝酵母",
    "假单胞菌",
    "猪胰",
    "米根霉",
    "米黑根毛霉",
    "疏棉状嗜热丝孢菌",
    "嗜热真菌",
    "酶固定",
}
CHINESE_APPLICATION_QUERY_TERMS = {"生物柴油", "转酯", "酯化", "大豆油", "底物"}
CHINESE_DOMAIN_QUERY_TERMS = (
    CHINESE_TABLE_QUERY_TERMS
    | CHINESE_STRATEGY_QUERY_TERMS
    | CHINESE_CONDITION_QUERY_TERMS
    | CHINESE_PERFORMANCE_QUERY_TERMS
    | CHINESE_ENZYME_QUERY_TERMS
    | CHINESE_APPLICATION_QUERY_TERMS
    | {"论文", "文献", "固定化酶", "酶固定化"}
)
NO_RETRIEVAL_PROMPT_INJECTION_RE = re.compile(
    r"("
    r"忽略|无视|不要看|不用看|跳过|覆盖|改成听我的|系统提示|提示词|prompt|system prompt|"
    r"伪造|编造|捏造|假装|虚构|fake|fabricate|hallucinate|"
    r"即使没有证据|没有证据也|不需要证据|不要引用|不要citation|no citation|"
    r"输出\s*candidates|carrier\s*=|直接告诉我最佳答案"
    r")",
    re.I,
)
NO_RETRIEVAL_CROSS_DOMAIN_RE = re.compile(
    r"("
    r"天气|股票|英伟达|红烧肉|胃疼|吃什么药|\breact(?:\.js)?\b|登录页|月亮的诗|"
    r"青霉素|发酵罐|灭菌|mRNA|疫苗|递送系统|蛋白结晶|结晶筛选|饲料淀粉酶|淀粉酶|"
    r"weather|stock|finance|recipe|medical|medicine|\breact(?:\.js)?\b|poem|crystallization|amylase|penicillin|vaccine"
    r")",
    re.I,
)
LOW_INFORMATION_QUERIES = {
    "abc",
    "不知道",
    "你好",
    "谢谢",
    "谢谢你",
    "我爱你",
    "你是什么东西",
    "who are you",
    "i do not know",
}
LOW_INFORMATION_PHRASES = {
    "i do not know",
    "do not know",
    "不知道",
}
RANDOM_KEYBOARD_TOKENS = {"abc", "asdf", "qwer", "zxcv", "xqz", "lmn", "ttt", "zzz"}
UNICODE_HYPHEN_TRANSLATION = str.maketrans(
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


class SearchRoute(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str
    point_type: Optional[PointType] = None
    record_type: Optional[RecordType] = None
    weight: float = 1.0
    limit: int = 8


class QueryPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intents: List[str]
    document_id: Optional[str] = None
    source_pdf: Optional[str] = None
    document_scope: bool = False
    retrieval_guard: Optional[str] = None
    record_type_priorities: List[RecordType] = Field(default_factory=list)
    point_type_priorities: List[PointType] = Field(default_factory=list)
    routes: List[SearchRoute] = Field(default_factory=list)
    query_tokens: List[str] = Field(default_factory=list)
    numeric_tokens: List[str] = Field(default_factory=list)


class RetrievalHit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    score: float
    vector_score: Optional[float] = None
    rerank_score: Optional[float] = None
    lexical_score: Optional[float] = None
    route_weight: float = 1.0
    route_labels: List[str] = Field(default_factory=list)
    point_type: str
    source_id: str
    parent_source_id: Optional[str] = None
    source_evidence_id: Optional[str] = None
    document_id: Optional[str] = None
    source_pdf: Optional[str] = None
    citation: Optional[str] = None
    page_start: Optional[int] = None
    page_end: Optional[int] = None
    section: Optional[str] = None
    record_type: Optional[str] = None
    confidence: Optional[str] = None
    candidate_source: Optional[str] = None
    curation_schema_version: Optional[str] = None
    curation_status: Optional[str] = None
    curation_reason: Optional[str] = None
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[str] = None
    qa_status: Optional[str] = None
    qa_flags: List[str] = Field(default_factory=list)
    quality_flags: List[str] = Field(default_factory=list)
    review_reasons: List[str] = Field(default_factory=list)
    requires_review: bool = False
    usable_for_ranking: bool = False
    extracted: Dict[str, Any] = Field(default_factory=dict)
    metrics: List[Dict[str, Any]] = Field(default_factory=list)
    text: str
    embedding_text: Optional[str] = None
    source_chunk_text: Optional[str] = None


class RetrievalResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str
    collection: str
    embedding_model: str
    top_k: int
    usable_only: bool
    point_type: Optional[str] = None
    query_plan: Optional[QueryPlan] = None
    hits: List[RetrievalHit]

    def context_text(self, max_chars_per_hit: int = 900) -> str:
        blocks = []
        for index, hit in enumerate(self.hits, start=1):
            text = (hit.source_chunk_text or hit.text)[:max_chars_per_hit]
            blocks.append(
                "\n".join(
                    [
                        f"[{index}] score={hit.score:.4f} type={hit.point_type} record_type={hit.record_type or '-'}",
                        f"source_id={hit.source_id} citation={hit.citation or '-'} usable={hit.usable_for_ranking} flags={hit.quality_flags}",
                        f"extracted={hit.extracted}",
                        f"metrics={hit.metrics}",
                        f"text={text}",
                    ]
                )
            )
        return "\n\n".join(blocks)


class EvidenceRetriever:
    def __init__(
        self,
        qdrant_config: QdrantConfig,
        embedding_model: Optional[Union[HashEmbeddingModel, SentenceEmbeddingModel]] = None,
    ) -> None:
        self.qdrant_config = qdrant_config
        self.embedding_model = embedding_model or HashEmbeddingModel(HashEmbeddingConfig())

    def retrieve(
        self,
        query: str,
        top_k: int = 8,
        point_type: Optional[PointType] = None,
        usable_only: bool = True,
    ) -> RetrievalResponse:
        guard_plan = build_query_plan(query, top_k=top_k, point_type=point_type)
        guard_reason = classify_no_retrieval_query(query, guard_plan)
        if guard_reason:
            guarded_plan = guard_plan.model_copy(
                update={
                    "retrieval_guard": guard_reason,
                    "intents": dedupe_ordered([*guard_plan.intents, "no_answer"]),
                }
            )
            return RetrievalResponse(
                query=query,
                collection=self.qdrant_config.collection,
                embedding_model=self.embedding_model.name,
                top_k=top_k,
                usable_only=usable_only,
                point_type=point_type,
                query_plan=guarded_plan,
                hits=[],
            )

        expanded_query = expand_query_for_retrieval(query)
        plan = build_query_plan(expanded_query, top_k=top_k, point_type=point_type)
        original_embedding_query = strip_document_scope_terms(query) if plan.document_scope else query
        expanded_embedding_query = strip_document_scope_terms(expanded_query) if plan.document_scope else expanded_query
        vector_queries = [
            item
            for item in dedupe_ordered([original_embedding_query.strip(), expanded_embedding_query.strip()])
            if item
        ]
        if not vector_queries:
            vector_queries = [query]
        with QdrantRestClient(self.qdrant_config) as client:
            hits = []
            for vector_index, vector_query in enumerate(vector_queries):
                query_vector = self.embedding_model.embed(vector_query)
                route_prefix = "expanded" if vector_index > 0 else "original"
                for route in plan.routes:
                    raw_hits = client.search(
                        vector=query_vector,
                        top_k=max(route.limit, 1),
                        query_filter=build_qdrant_filter(
                            point_type=route.point_type,
                            usable_only=usable_only,
                            record_type=route.record_type,
                            document_id=plan.document_id,
                            source_pdf=plan.source_pdf,
                        ),
                    )
                    routed = route.model_copy(update={"label": f"{route_prefix}:{route.label}"})
                    hits.extend(raw_hit_to_retrieval_hit(raw_hit, routed) for raw_hit in raw_hits)
                if plan.document_scope:
                    document_filter_payload = build_qdrant_filter(
                        point_type=point_type,
                        usable_only=usable_only,
                        document_id=plan.document_id,
                        source_pdf=plan.source_pdf,
                    )
                    for raw_point in client.scroll_points(
                        document_filter_payload or {},
                        limit=max(top_k * 12, 128),
                        with_vector=True,
                    ):
                        vector = raw_point.get("vector") or []
                        raw_hit = {
                            "payload": raw_point.get("payload") or {},
                            "score": cosine_similarity(query_vector, vector) if vector else 0.0,
                        }
                        hits.append(
                            raw_hit_to_retrieval_hit(
                                raw_hit,
                                SearchRoute(label=f"{route_prefix}:document_scan", weight=1.45),
                            )
                        )
        hits = merge_route_hits(hits)
        rerank_query = expanded_embedding_query or expanded_query or query
        hits = rerank_hits(rerank_query, hits, plan)[:top_k]
        return RetrievalResponse(
            query=query,
            collection=self.qdrant_config.collection,
            embedding_model=self.embedding_model.name,
            top_k=top_k,
            usable_only=usable_only,
            point_type=point_type,
            query_plan=plan,
            hits=hits,
        )


def build_qdrant_filter(
    point_type: Optional[str],
    usable_only: bool,
    record_type: Optional[str] = None,
    document_id: Optional[str] = None,
    source_pdf: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    must: List[Dict[str, Any]] = []
    if point_type:
        must.append({"key": "point_type", "match": {"value": point_type}})
    if record_type:
        must.append({"key": "record_type", "match": {"value": record_type}})
    if document_id:
        must.append({"key": "document_id", "match": {"value": document_id}})
    elif source_pdf:
        must.append({"key": "source_pdf", "match": {"value": source_pdf}})
    if usable_only:
        must.append({"key": "usable_for_ranking", "match": {"value": True}})
    if not must:
        return None
    return {"must": must}


def raw_hit_to_retrieval_hit(raw_hit: Dict[str, Any], route: Optional[SearchRoute] = None) -> RetrievalHit:
    payload = raw_hit.get("payload") or {}
    vector_score = float(raw_hit.get("score") or 0.0)
    route_label = route.label if route else "default"
    route_weight = route.weight if route else 1.0
    return RetrievalHit(
        score=vector_score,
        vector_score=vector_score,
        route_weight=route_weight,
        route_labels=[route_label],
        point_type=str(payload.get("point_type") or ""),
        source_id=str(payload.get("source_id") or ""),
        parent_source_id=payload.get("parent_source_id"),
        source_evidence_id=payload.get("source_evidence_id"),
        document_id=payload.get("document_id"),
        source_pdf=payload.get("source_pdf"),
        citation=payload.get("citation"),
        page_start=payload.get("page_start"),
        page_end=payload.get("page_end"),
        section=payload.get("section"),
        record_type=payload.get("record_type"),
        confidence=payload.get("confidence"),
        candidate_source=payload.get("candidate_source"),
        curation_schema_version=payload.get("curation_schema_version"),
        curation_status=payload.get("curation_status"),
        curation_reason=payload.get("curation_reason"),
        reviewed_by=payload.get("reviewed_by"),
        reviewed_at=payload.get("reviewed_at"),
        qa_status=payload.get("qa_status"),
        qa_flags=list(payload.get("qa_flags") or []),
        quality_flags=list(payload.get("quality_flags") or []),
        review_reasons=list(payload.get("review_reasons") or []),
        requires_review=bool(payload.get("requires_review")),
        usable_for_ranking=bool(payload.get("usable_for_ranking")),
        extracted=dict(payload.get("extracted") or {}),
        metrics=list(payload.get("metrics") or []),
        text=str(payload.get("text") or ""),
        embedding_text=payload.get("embedding_text"),
    )


def merge_route_hits(hits: Sequence[RetrievalHit]) -> List[RetrievalHit]:
    merged: Dict[Tuple[str, str, str, str], RetrievalHit] = {}
    for hit in hits:
        key = (
            hit.point_type,
            hit.record_type or "",
            hit.document_id or "",
            hit.source_id,
        )
        existing = merged.get(key)
        if existing is None:
            merged[key] = hit
            continue
        route_labels = sorted(set(existing.route_labels) | set(hit.route_labels))
        route_weight = max(existing.route_weight, hit.route_weight)
        if (hit.vector_score or hit.score) > (existing.vector_score or existing.score):
            merged[key] = hit.model_copy(update={"route_labels": route_labels, "route_weight": route_weight})
        else:
            merged[key] = existing.model_copy(update={"route_labels": route_labels, "route_weight": route_weight})
    return list(merged.values())


def rerank_hits(query: str, hits: List[RetrievalHit], plan: Optional[QueryPlan] = None) -> List[RetrievalHit]:
    plan = plan or build_query_plan(query, top_k=len(hits) or 8)
    query_token_list = normalize_tokens(query)
    query_tokens = set(query_token_list)
    query_profile = lexical_profile(query, query_token_list)
    query_enzyme_alias_keys = matched_enzyme_alias_keys(query)
    query_condition_values = condition_value_terms(query)
    query_has_table_intent = "table" in plan.intents
    query_has_evidence_intent = bool({"strategy", "condition", "performance", "enzyme"} & set(plan.intents))
    strategy_is_primary = bool(plan.record_type_priorities and plan.record_type_priorities[0] == "immobilization_strategy")
    reranked: List[RetrievalHit] = []
    for hit in hits:
        searchable = hit_searchable_text(hit)
        text_profile = lexical_profile(searchable)
        text_enzyme_alias_keys = matched_enzyme_alias_keys(searchable)
        text_condition_values = condition_value_terms(hit.text or hit.source_chunk_text or "")
        text_tokens = set(normalize_tokens(searchable))
        overlap = len(query_tokens & text_tokens) / max(len(query_tokens), 1)
        numeric_overlap = len(query_profile["numeric_tokens"] & text_profile["numeric_tokens"])
        condition_value_overlap = len(query_condition_values & text_condition_values)
        lexical_score = compute_lexical_score(query_profile, text_profile)
        bonus = 0.0
        if hit.route_weight > 1.0:
            bonus += min(0.12, 0.04 * (hit.route_weight - 1.0))
        if hit.record_type in plan.record_type_priorities:
            rank = plan.record_type_priorities.index(hit.record_type)
            bonus += max(0.0, 0.12 - 0.025 * rank)
        if hit.point_type in plan.point_type_priorities:
            rank = plan.point_type_priorities.index(hit.point_type)  # type: ignore[arg-type]
            bonus += max(0.0, 0.05 - 0.015 * rank)
        if query_has_table_intent and hit.point_type in {"table_record", "evidence_record"}:
            bonus += 0.08
        if query_has_table_intent and hit.record_type == "table_comparison_row":
            bonus += 0.12
        if query_has_evidence_intent and hit.point_type == "evidence_record":
            bonus += 0.05
        if "condition" in plan.intents and hit.record_type == "formulation_condition":
            bonus += 0.20
        elif "condition" in plan.intents and plan.numeric_tokens and hit.record_type != "formulation_condition":
            bonus -= 0.06
        if "performance" in plan.intents and hit.record_type in {"performance_metric", "table_comparison_row"}:
            bonus += 0.08
        if "strategy" in plan.intents and hit.record_type == "immobilization_strategy":
            bonus += 0.08
            if strategy_is_primary:
                bonus += 0.10
        if numeric_overlap:
            bonus += min(0.08, 0.025 * numeric_overlap)
        if condition_value_overlap:
            bonus += min(0.34, 0.28 * condition_value_overlap)
        if query_enzyme_alias_keys:
            enzyme_overlap = query_enzyme_alias_keys & text_enzyme_alias_keys
            if enzyme_overlap:
                bonus += min(0.24, 0.12 * len(enzyme_overlap))
            elif text_enzyme_alias_keys:
                bonus -= 0.05
        if hit.confidence == "high":
            bonus += 0.03
        elif hit.confidence == "low":
            bonus -= 0.03
        flags = set(hit.quality_flags) | set(hit.qa_flags)
        if flags:
            bad_flags = BAD_QUALITY_FLAGS & flags
            bonus -= min(0.16, 0.025 * len(flags) + 0.05 * len(bad_flags))
        if hit.qa_status == "fail":
            bonus -= 0.16
        if hit.requires_review:
            bonus -= 0.12
        rerank_score = float(hit.score) + bonus + lexical_score + 0.08 * overlap
        reranked.append(
            hit.model_copy(
                update={
                    "score": rerank_score,
                    "rerank_score": rerank_score,
                    "lexical_score": lexical_score,
                }
            )
        )
    return apply_result_diversity(reranked, document_scoped=bool(plan.document_scope))


def normalize_tokens(text: str) -> List[str]:
    normalized = normalize_lexical_text(text)
    return [match.group(0).lower().strip("-") for match in TOKEN_RE.finditer(normalized) if match.group(0).strip("-")]


def normalize_lexical_text(text: str) -> str:
    normalized = (text or "").translate(UNICODE_HYPHEN_TRANSLATION)
    # MinerU/OCR occasionally splits the enzyme token before @material, e.g. "Lipa se@NKMOF-101-Mn".
    normalized = re.sub(r"\blipa\s+se\s*@", "lipase@", normalized, flags=re.I)
    alias_terms = matched_enzyme_alias_terms(normalized)
    if alias_terms:
        normalized = " ".join([normalized, *alias_terms])
    chinese_aliases = {
        "脂肪酶": " lipase ",
        "生物柴油": " biodiesel ",
        "大豆油": " soybean oil ",
        "乙醇": " ethanol ",
        "转酯": " transesterification ",
        "重复使用": " reusability reuse cycles ",
        "重复用": " reusability reuse cycles ",
        "复用": " reusability reuse cycles ",
        "更稳": " stability retained activity ",
        "稳定性": " stability retained activity ",
    }
    for raw, replacement in chinese_aliases.items():
        normalized = normalized.replace(raw, replacement)
    return normalized


def apply_result_diversity(hits: Sequence[RetrievalHit], document_scoped: bool = False) -> List[RetrievalHit]:
    sorted_hits = sorted(
        hits,
        key=lambda item: item.rerank_score if item.rerank_score is not None else item.score,
        reverse=True,
    )
    parent_counts: Dict[str, int] = {}
    document_counts: Dict[str, int] = {}
    document_table_counts: Dict[str, int] = {}
    seen_fingerprints: set[str] = set()
    diversified: List[RetrievalHit] = []
    for hit in sorted_hits:
        fingerprint = duplicate_hit_fingerprint(hit)
        if not document_scoped and fingerprint and fingerprint in seen_fingerprints:
            continue
        if not document_scoped and fingerprint:
            seen_fingerprints.add(fingerprint)

        parent_key = result_parent_key(hit)
        duplicate_penalty = 0.0
        if parent_key:
            seen = parent_counts.get(parent_key, 0)
            if seen:
                duplicate_penalty += min(0.70, 0.35 * seen)
            parent_counts[parent_key] = seen + 1

        document_key = hit.document_id or hit.source_pdf or ""
        if document_key and not document_scoped:
            seen = document_counts.get(document_key, 0)
            if seen:
                duplicate_penalty += min(0.28, 0.08 * seen)
            document_counts[document_key] = seen + 1

        if document_key and hit.record_type == "table_comparison_row":
            table_seen = document_table_counts.get(document_key, 0)
            if table_seen:
                duplicate_penalty += min(0.54, 0.18 * table_seen)
            document_table_counts[document_key] = table_seen + 1

        if duplicate_penalty <= 0:
            diversified.append(hit)
            continue
        adjusted_score = (hit.rerank_score if hit.rerank_score is not None else hit.score) - duplicate_penalty
        diversified.append(hit.model_copy(update={"score": adjusted_score, "rerank_score": adjusted_score}))
    return sorted(
        diversified,
        key=lambda item: item.rerank_score if item.rerank_score is not None else item.score,
        reverse=True,
    )


def result_parent_key(hit: RetrievalHit) -> str:
    if hit.parent_source_id:
        return f"{hit.document_id or ''}:{hit.parent_source_id}"
    table_id = hit.extracted.get("table_id") if isinstance(hit.extracted, dict) else None
    if table_id:
        return f"{hit.document_id or ''}:{table_id}"
    return ""


def duplicate_hit_fingerprint(hit: RetrievalHit) -> str:
    text = normalize_duplicate_text(hit.text or hit.source_chunk_text or hit.embedding_text or "")
    if len(text) < 80:
        return ""
    return f"{hit.record_type or hit.point_type}:{text[:520]}"


def normalize_duplicate_text(text: str) -> str:
    normalized = normalize_lexical_text(text).lower()
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def hit_searchable_text(hit: RetrievalHit) -> str:
    return " ".join(
        [
            hit.section or "",
            hit.record_type or "",
            hit.text or "",
            hit.embedding_text or "",
            hit.source_chunk_text or "",
            json.dumps(hit.extracted, ensure_ascii=False, sort_keys=True),
            json.dumps(hit.metrics, ensure_ascii=False, sort_keys=True),
        ]
    )


def lexical_profile(text: str, tokens: Optional[Sequence[str]] = None) -> Dict[str, set[str]]:
    normalized_text = normalize_lexical_text(text)
    token_list = list(tokens or normalize_tokens(normalized_text))
    expanded_tokens = expand_lexical_tokens(token_list)
    meaningful_tokens = {token for token in expanded_tokens if is_meaningful_lexical_token(token)}
    important_tokens = {token for token in meaningful_tokens if is_important_lexical_token(token)}
    numeric_tokens = {token for token in expanded_tokens if is_numeric_lexical_token(token)}
    domain_tokens = {token for token in important_tokens if is_domain_lexical_token(token)}
    material_tokens = {token for token in domain_tokens if is_material_lexical_token(token)}
    rare_material_tokens = {
        token for token in material_tokens if token not in COMMON_MATERIAL_TOKENS and token not in BROAD_DOMAIN_TOKENS
    }
    constructs = at_constructs(normalized_text)
    rare_at_constructs = {
        construct
        for construct in constructs
        if any(part in rare_material_tokens for part in construct.split("@")[1:])
    }
    return {
        "tokens": set(expanded_tokens),
        "meaningful_tokens": meaningful_tokens,
        "important_tokens": important_tokens,
        "numeric_tokens": numeric_tokens,
        "domain_tokens": domain_tokens,
        "material_tokens": material_tokens,
        "rare_material_tokens": rare_material_tokens,
        "at_constructs": constructs,
        "rare_at_constructs": rare_at_constructs,
        "phrases": lexical_phrases(expanded_tokens),
    }


def expand_lexical_tokens(tokens: Sequence[str]) -> List[str]:
    expanded: List[str] = []
    for token in tokens:
        value = canonical_lexical_token(token)
        if not value:
            continue
        expanded.append(value)
        if value in NUMBER_WORDS:
            expanded.append(NUMBER_WORDS[value])
        if value.endswith("%"):
            expanded.append(value.rstrip("%"))
        if "-" in value:
            compact = value.replace("-", "")
            if compact:
                expanded.append(compact)
    return expanded


def canonical_lexical_token(token: str) -> str:
    value = (token or "").lower().strip("-_.,;:()[]{}")
    if not value:
        return ""
    value = value.replace("°", "")
    if re.fullmatch(r"\d+\.0+", value):
        value = value.split(".", 1)[0]
    return value


def is_meaningful_lexical_token(token: str) -> bool:
    return len(token) >= 2 and token not in LEXICAL_STOPWORDS


def is_important_lexical_token(token: str) -> bool:
    return (
        token in DOMAIN_QUERY_TERMS
        or token in NUMBER_WORDS
        or token in UNIT_TOKENS
        or bool(re.search(r"\d", token))
        or "-" in token
        or len(token) >= 5
    )


def is_numeric_lexical_token(token: str) -> bool:
    return bool(re.fullmatch(r"\d+(?:\.\d+)?%?", token))


def is_domain_lexical_token(token: str) -> bool:
    return (
        token in DOMAIN_QUERY_TERMS
        or bool(MATERIAL_RE.search(token))
        or bool(re.search(r"(?:zif|uio|mil|mof|hkust|btc|fe3o4|nkmof|nu|mcm|pnipam|calb|cal-b|bcl|ppl|crl|tll)", token))
    )


def is_material_lexical_token(token: str) -> bool:
    return bool(
        MATERIAL_RE.search(token)
        or re.search(r"(?:zif|uio|mil|mof|hkust|btc|fe3o4|nkmof|nu-?\d|mcm-?\d|pnipam)", token)
    )


def at_constructs(text: str) -> set[str]:
    constructs: set[str] = set()
    for match in AT_CONSTRUCT_RE.finditer(text or ""):
        value = re.sub(r"\s+", "", match.group(0).lower())
        value = canonical_lexical_token(value)
        if not value or "@" not in value:
            continue
        constructs.add(value)
        parts = [canonical_lexical_token(part) for part in value.split("@") if canonical_lexical_token(part)]
        for index in range(1, len(parts)):
            constructs.add("@".join(parts[: index + 1]))
    return constructs


def lexical_phrases(tokens: Sequence[str]) -> set[str]:
    meaningful = [token for token in tokens if is_meaningful_lexical_token(token)]
    phrases: set[str] = set()
    for width in (2, 3):
        for index in range(0, max(0, len(meaningful) - width + 1)):
            window = meaningful[index : index + width]
            if any(is_important_lexical_token(token) for token in window):
                phrases.add(" ".join(window))
    return phrases


def compute_lexical_score(query_profile: Dict[str, set[str]], text_profile: Dict[str, set[str]]) -> float:
    meaningful_ratio = overlap_ratio(query_profile["meaningful_tokens"], text_profile["meaningful_tokens"])
    important_ratio = overlap_ratio(query_profile["important_tokens"], text_profile["important_tokens"])
    numeric_ratio = overlap_ratio(query_profile["numeric_tokens"], text_profile["numeric_tokens"])
    domain_ratio = overlap_ratio(query_profile["domain_tokens"], text_profile["domain_tokens"])
    material_ratio = overlap_ratio(query_profile.get("material_tokens", set()), text_profile.get("material_tokens", set()))
    rare_material_ratio = overlap_ratio(
        query_profile.get("rare_material_tokens", set()),
        text_profile.get("rare_material_tokens", set()),
    )
    construct_ratio = overlap_ratio(query_profile.get("at_constructs", set()), text_profile.get("at_constructs", set()))
    rare_construct_ratio = overlap_ratio(
        query_profile.get("rare_at_constructs", set()),
        text_profile.get("rare_at_constructs", set()),
    )
    phrase_ratio = overlap_ratio(query_profile["phrases"], text_profile["phrases"])
    score = (
        0.06 * meaningful_ratio
        + 0.10 * important_ratio
        + 0.12 * numeric_ratio
        + 0.10 * domain_ratio
        + 0.08 * material_ratio
        + 0.14 * rare_material_ratio
        + 0.08 * construct_ratio
        + 0.18 * rare_construct_ratio
        + 0.04 * phrase_ratio
    )
    return min(0.48, score)


def overlap_ratio(expected: set[str], actual: set[str]) -> float:
    if not expected:
        return 0.0
    return len(expected & actual) / len(expected)


def build_query_plan(query: str, top_k: int = 8, point_type: Optional[PointType] = None) -> QueryPlan:
    document_id, source_pdf = extract_document_scope(query)
    planning_query = strip_document_scope_terms(query) if document_id else query
    tokens = normalize_tokens(planning_query or query)
    token_set = set(tokens)
    lowered_query = normalize_lexical_text(planning_query or query).lower()
    intents: List[str] = []
    record_types: List[RecordType] = []
    point_types: List[PointType] = []

    if document_id:
        intents.append("document_scope")

    if (token_set & TABLE_QUERY_TERMS) or contains_any(lowered_query, CHINESE_TABLE_QUERY_TERMS):
        intents.append("table")
        record_types.append("table_comparison_row")
        point_types.extend(["evidence_record", "table_record"])
    if (token_set & PERFORMANCE_QUERY_TERMS) or contains_any(lowered_query, CHINESE_PERFORMANCE_QUERY_TERMS):
        intents.append("performance")
        record_types.extend(["performance_metric", "table_comparison_row"])
        point_types.extend(["evidence_record", "table_record"])
    if (
        (token_set & CONDITION_QUERY_TERMS)
        or CONDITION_VALUE_RE.search(planning_query or query)
        or contains_any(lowered_query, CHINESE_CONDITION_QUERY_TERMS)
    ):
        intents.append("condition")
        record_types.append("formulation_condition")
        point_types.append("evidence_record")
    if (
        (token_set & STRATEGY_QUERY_TERMS)
        or MATERIAL_RE.search(planning_query or query)
        or contains_any(lowered_query, CHINESE_STRATEGY_QUERY_TERMS)
        or re.search(r"\b(?:zif8|zif-?8|uio66|uio-?66|mof)\b", lowered_query)
    ):
        intents.append("strategy")
        record_types.append("immobilization_strategy")
        point_types.extend(["evidence_record", "rag_chunk"])
    if (token_set & ENZYME_QUERY_TERMS) or contains_any(lowered_query, CHINESE_ENZYME_QUERY_TERMS):
        intents.append("enzyme")
        record_types.append("enzyme_identity")
    if (token_set & APPLICATION_QUERY_TERMS) or contains_any(lowered_query, CHINESE_APPLICATION_QUERY_TERMS):
        intents.append("application")
    if not intents:
        intents.append("general")
    if not point_types:
        point_types.extend(["evidence_record", "rag_chunk"])

    record_types = prioritize_record_types(dedupe_ordered(record_types), lowered_query)
    point_types = dedupe_ordered(point_types)
    numeric_tokens = [token for token in tokens if re.search(r"\d", token)]
    routes = build_search_routes(
        top_k=top_k,
        point_type=point_type,
        record_types=record_types,
        point_types=point_types,
        intents=intents,
        document_scoped=bool(document_id),
    )
    return QueryPlan(
        intents=dedupe_ordered(intents),
        document_id=document_id,
        source_pdf=source_pdf,
        document_scope=bool(document_id),
        record_type_priorities=record_types,
        point_type_priorities=point_types,
        routes=routes,
        query_tokens=tokens,
        numeric_tokens=numeric_tokens,
    )


def build_search_routes(
    top_k: int,
    point_type: Optional[PointType],
    record_types: Sequence[RecordType],
    point_types: Sequence[PointType],
    intents: Sequence[str],
    document_scoped: bool = False,
) -> List[SearchRoute]:
    base_limit = max(top_k * (6 if document_scoped else 3), top_k, 24 if document_scoped else 8)
    record_limit = max(top_k * (4 if document_scoped else 2), 16 if document_scoped else 6)
    routes: List[SearchRoute] = []
    if point_type:
        routes.append(
            SearchRoute(
                label=f"explicit:{point_type}",
                point_type=point_type,
                limit=base_limit,
                weight=1.0,
            )
        )
        if point_type == "evidence_record":
            for index, record_type in enumerate(record_types[:4]):
                routes.append(
                    SearchRoute(
                        label=f"explicit:{point_type}:{record_type}",
                        point_type=point_type,
                        record_type=record_type,
                        limit=record_limit,
                        weight=max(1.0, 2.0 - 0.2 * index),
                    )
                )
        return routes

    for index, record_type in enumerate(record_types[:5]):
        routes.append(
            SearchRoute(
                label=f"record_type:{record_type}",
                point_type="evidence_record",
                record_type=record_type,
                limit=record_limit,
                weight=max(1.0, 2.2 - 0.2 * index),
            )
        )
    for index, route_point_type in enumerate(point_types[:3]):
        routes.append(
            SearchRoute(
                label=f"point_type:{route_point_type}",
                point_type=route_point_type,
                limit=base_limit,
                weight=max(1.0, 1.35 - 0.12 * index),
            )
        )
    routes.append(SearchRoute(label="broad", point_type=None, limit=base_limit, weight=1.0))
    if "table" in intents and not any(route.point_type == "table_record" for route in routes):
        routes.append(SearchRoute(label="point_type:table_record", point_type="table_record", limit=base_limit, weight=1.2))
    return routes


def prioritize_record_types(record_types: List[RecordType], lowered_query: str) -> List[RecordType]:
    if not record_types:
        return record_types
    if "immobilization_strategy" in record_types and contains_any(lowered_query, MECHANISTIC_STRATEGY_MARKERS):
        return ["immobilization_strategy", *[item for item in record_types if item != "immobilization_strategy"]]
    formulation_markers = {
        "formulation",
        "optimize_formulation",
        "loading",
        "ph",
        "buffer",
        "adsorption",
        "配方",
        "条件",
        "优化",
        "制备",
    }
    if "formulation_condition" in record_types and contains_any(lowered_query, formulation_markers):
        return ["formulation_condition", *[item for item in record_types if item != "formulation_condition"]]
    return record_types


def extract_document_scope(query: str) -> Tuple[Optional[str], Optional[str]]:
    document_ids = extract_document_ids(query)
    if len(document_ids) != 1:
        return None, None
    document_id = document_ids[0]
    return document_id, f"{document_id}.pdf"


def extract_document_ids(query: str) -> List[str]:
    seen: set[str] = set()
    document_ids: List[str] = []
    for match in EXPLICIT_DOCUMENT_ID_RE.finditer(query or ""):
        document_id = canonical_document_id(match.group(1), match.group(2))
        if document_id in seen:
            continue
        seen.add(document_id)
        document_ids.append(document_id)
    for match in DOCUMENT_ID_RE.finditer(query or ""):
        if is_probable_non_document_id_match(query or "", match):
            continue
        document_id = canonical_document_id(match.group(1), match.group(2))
        if document_id in seen:
            continue
        seen.add(document_id)
        document_ids.append(document_id)
    return document_ids


def canonical_document_id(prefix: str, digits: str) -> str:
    return f"{prefix.upper()}{int(digits)}"


def strip_document_scope_terms(query: str) -> str:
    stripped = EXPLICIT_DOCUMENT_ID_RE.sub(" ", query or "")
    stripped = DOCUMENT_ID_RE.sub(lambda match: match.group(0) if is_probable_non_document_id_match(stripped, match) else " ", stripped)
    stripped = re.sub(r"\s+", " ", stripped)
    return stripped.strip()


def is_probable_non_document_id_match(query: str, match: re.Match[str]) -> bool:
    if match.group(3):
        return False
    before = query[max(0, match.start() - 48) : match.start()].lower()
    immediate_before = before[-16:]
    if re.search(r"(?:\bsp\.?\s*|\bstrain\s*|\bisolate\s*)$", immediate_before):
        return True
    return False


def classify_no_retrieval_query(query: str, plan: Optional[QueryPlan] = None) -> Optional[str]:
    text = (query or "").strip()
    if not text:
        return "empty_query"
    if NO_RETRIEVAL_PROMPT_INJECTION_RE.search(text):
        return "prompt_injection"
    if plan and plan.document_scope:
        return None
    if NO_RETRIEVAL_CROSS_DOMAIN_RE.search(text):
        return "out_of_domain"
    if is_low_information_query(text):
        return "low_information"
    if not has_lipase_immobilization_domain_signal(text) and is_general_assistant_request(text):
        return "out_of_domain"
    return None


def is_low_information_query(query: str) -> bool:
    normalized = re.sub(r"\s+", " ", query.strip().lower())
    normalized = normalized.strip(" ?？!！。.,;；:")
    if normalized in LOW_INFORMATION_QUERIES:
        return True
    if any(phrase in normalized for phrase in LOW_INFORMATION_PHRASES):
        return True
    if not normalized:
        return True
    if re.fullmatch(r"[0-9]+", normalized):
        return True
    if re.fullmatch(r"\d+\s*(?:加|plus|\+)\s*\d+.*", normalized):
        return True
    tokens = normalize_tokens(normalized)
    if tokens and set(tokens) <= RANDOM_KEYBOARD_TOKENS:
        return True
    if len(tokens) == 1 and tokens[0] in RANDOM_KEYBOARD_TOKENS:
        return True
    return False


def has_lipase_immobilization_domain_signal(query: str) -> bool:
    lowered = normalize_lexical_text(query).lower()
    tokens = set(normalize_tokens(lowered))
    if matched_enzyme_alias_keys(query):
        return True
    if tokens & DOMAIN_QUERY_TERMS:
        return True
    if contains_any(lowered, CHINESE_DOMAIN_QUERY_TERMS):
        return True
    if MATERIAL_RE.search(query):
        return True
    return bool(re.search(r"\b(?:zif8|zif-?8|uio66|uio-?66|mof|calb|cal-b|bcl|lipase)\b", lowered))


def is_general_assistant_request(query: str) -> bool:
    lowered = query.lower()
    if re.search(r"(怎么|如何|帮我|给我|是什么|多少|吗|？|\?|what|how|write|tell me|who are you)", lowered):
        return True
    return len(normalize_tokens(lowered)) <= 3


def contains_any(text: str, terms: Sequence[str]) -> bool:
    return any(term in text for term in terms)


def condition_value_terms(text: str) -> set[str]:
    normalized = normalize_lexical_text(text or "").lower().replace("°c", " c ")
    terms: set[str] = set()
    for label, pattern in CONDITION_VALUE_PATTERNS:
        for match in pattern.finditer(normalized):
            value = canonical_lexical_token(match.group(1)).rstrip("%")
            if value:
                terms.add(f"{label}:{value}")
    return terms


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = 0.0
    left_norm = 0.0
    right_norm = 0.0
    for left_value, right_value in zip(left, right):
        dot += float(left_value) * float(right_value)
        left_norm += float(left_value) * float(left_value)
        right_norm += float(right_value) * float(right_value)
    if left_norm <= 0 or right_norm <= 0:
        return 0.0
    return dot / (math.sqrt(left_norm) * math.sqrt(right_norm))


def dedupe_ordered(items: Sequence[Any]) -> List[Any]:
    seen = set()
    output = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        output.append(item)
    return output
