from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from enzyme_recommender.generators import ChatMessage, GenerationRequest, GenerationResponse
from enzyme_recommender.literature import ExternalLiteratureResult
from enzyme_recommender.rag.retrieval import RetrievalHit, RetrievalResponse, build_query_plan, classify_no_retrieval_query
from enzyme_recommender.recommendation.enzyme import parse_json_object, retrieval_guard_reason
from enzyme_recommender.recommendation.grounding import build_grounded_answer, build_no_answer_text
from enzyme_recommender.runtime import RuntimeServices


GeneralQAAnswerMode = Literal["direct", "troubleshooting", "literature_review", "experimental_design"]


class GeneralQARequest(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    question: str
    application_context: Optional[str] = None
    constraints: List[str] = Field(default_factory=list)
    answer_mode: GeneralQAAnswerMode = "direct"
    allow_model_prior: bool = True
    top_k: Optional[int] = None

    @field_validator("question")
    @classmethod
    def question_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("question must not be empty")
        return value.strip()


class GeneralQAResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    qa_id: str
    created_at: str
    question: str
    answer_mode: GeneralQAAnswerMode
    retrieval_query: str
    generator_provider: str
    generator_model: str
    answer: str
    evidence_summary: List[str] = Field(default_factory=list)
    reasoning_notes: List[str] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)
    suggested_next_steps: List[str] = Field(default_factory=list)
    evidence_hits: List[RetrievalHit]
    generation_content: str
    generation_json: Optional[Dict[str, Any]] = None


class GeneralQAService:
    def __init__(self, runtime: RuntimeServices) -> None:
        self.runtime = runtime

    def answer_general_qa(self, request: GeneralQARequest) -> GeneralQAResponse:
        retrieval = self.retrieve_evidence(request)
        external_literature = self.retrieve_external_literature(request, retrieval)
        generation = self.deterministic_generation_if_required(request, retrieval, external_literature)
        if generation is None:
            generation = self._generate_answer(request, retrieval, external_literature)
        return self.build_response(request, retrieval, generation, external_literature)

    def retrieve_evidence(self, request: GeneralQARequest) -> RetrievalResponse:
        requested_top_k = request.top_k or max(self.runtime.config.retrieval.top_k, 8)
        guard_query = build_general_qa_guard_query(request)
        guard_plan = build_query_plan(guard_query, top_k=requested_top_k)
        guard_reason = classify_general_qa_guard_query(guard_query, guard_plan)
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
                top_k=requested_top_k,
                usable_only=self.runtime.config.retrieval.usable_only,
                query_plan=guarded_plan,
                hits=[],
            )
        retrieval_query = build_general_qa_retrieval_query(request)
        return self.runtime.retriever().retrieve(
            query=retrieval_query,
            top_k=requested_top_k,
            usable_only=self.runtime.config.retrieval.usable_only,
        )

    def retrieve_external_literature(
        self,
        request: GeneralQARequest,
        retrieval: RetrievalResponse,
    ) -> Optional[ExternalLiteratureResult]:
        if retrieval_guard_reason(retrieval) or not should_use_external_literature(request):
            return None
        config = self.runtime.config.external_literature
        if not config.enabled or config.provider != "aminer_mcp":
            return None
        query = build_external_literature_query(request)
        client = self.runtime.external_literature()
        if client is None:
            return ExternalLiteratureResult(
                status="missing_token",
                query=query,
                message=f"missing env var: {config.auth_token_env}",
            )
        return client.search_papers(query, max_results=config.max_results)

    def deterministic_generation_if_required(
        self,
        request: GeneralQARequest,
        retrieval: RetrievalResponse,
        external_literature: Optional[ExternalLiteratureResult] = None,
    ) -> Optional[GenerationResponse]:
        reason = retrieval_guard_reason(retrieval)
        if reason:
            return deterministic_general_no_answer_generation(reason)
        if external_literature and external_literature.status == "success" and external_literature.items:
            return None
        if not retrieval.hits and not request.allow_model_prior:
            return deterministic_general_no_answer_generation("no_relevant_evidence")
        return None

    def build_generation_request(
        self,
        request: GeneralQARequest,
        retrieval: RetrievalResponse,
        external_literature: Optional[ExternalLiteratureResult] = None,
    ) -> GenerationRequest:
        config = self.runtime.config
        provider_config = config.generator_providers[config.generator.provider]
        return GenerationRequest(
            messages=[
                ChatMessage(role="system", content=SYSTEM_PROMPT),
                ChatMessage(role="user", content=build_general_qa_prompt(request, retrieval, external_literature)),
            ],
            model=provider_config.model,
            temperature=config.generator.temperature,
            response_format="json_object",
            timeout_seconds=config.generator.timeout_seconds,
            max_retries=config.generator.max_retries,
        )

    def build_stream_generation_request(
        self,
        request: GeneralQARequest,
        retrieval: RetrievalResponse,
        external_literature: Optional[ExternalLiteratureResult] = None,
    ) -> GenerationRequest:
        base_request = self.build_generation_request(request, retrieval, external_literature)
        return base_request.model_copy(
            update={
                "messages": [
                    ChatMessage(role="system", content=STREAM_SYSTEM_PROMPT),
                    ChatMessage(role="user", content=build_stream_general_qa_prompt(request, retrieval, external_literature)),
                ],
                "response_format": "text",
                "max_retries": 0,
            }
        )

    def build_response(
        self,
        request: GeneralQARequest,
        retrieval: RetrievalResponse,
        generation: GenerationResponse,
        external_literature: Optional[ExternalLiteratureResult] = None,
    ) -> GeneralQAResponse:
        generation_json = parse_json_object(generation.content)
        answer_payload = build_answer_payload(generation_json, request, retrieval, generation, external_literature)
        answer = answer_payload["answer"]
        return GeneralQAResponse(
            qa_id=make_general_qa_id(request, retrieval),
            created_at=datetime.now(timezone.utc).isoformat(),
            question=request.question,
            answer_mode=request.answer_mode,
            retrieval_query=build_general_qa_retrieval_query(request),
            generator_provider=generation.provider,
            generator_model=generation.model,
            answer=answer,
            evidence_summary=answer_payload["evidence_summary"],
            reasoning_notes=answer_payload["reasoning_notes"],
            limitations=answer_payload["limitations"],
            suggested_next_steps=answer_payload["suggested_next_steps"],
            evidence_hits=retrieval.hits,
            generation_content=answer,
            generation_json=generation_json,
        )

    def _generate_answer(
        self,
        request: GeneralQARequest,
        retrieval: RetrievalResponse,
        external_literature: Optional[ExternalLiteratureResult] = None,
    ) -> GenerationResponse:
        generator = self.runtime.generator()
        return generator.generate(self.build_generation_request(request, retrieval, external_literature))


SYSTEM_PROMPT = """你是一个面向酶固定化、MOF/ZIF 载体和微流控固定化实验的通用问答助手。
必须 evidence-first：有本地 evidence context 时优先基于证据回答，每个关键事实带 [1]、[2] reference index。
如果存在 External literature context，它来自 AMiner MCP 外部文献检索，只能用 AMiner-1、AMiner-2 这类标识引用；不得把外部 MCP 结果伪装成本地知识库直接证据。
如果 evidence context 不足但问题仍属于本领域，并且用户允许模型先验，可以给基于通用科学原理的推理；这类内容必须明确标注“模型推理，非知识库直接证据”。
不得宣称全局最优、唯一最佳或保证成功；涉及文献时效的问题必须说明检索范围和外部 MCP 结果仍需人工复核。
输出必须是 JSON object。"""


STREAM_SYSTEM_PROMPT = """你是一个面向酶固定化、MOF/ZIF 载体和微流控固定化实验的通用问答助手。
优先快速输出自然中文，不输出 JSON。有本地 evidence context 时关键事实必须带 [1]、[2] reference index；External literature context 只能用 AMiner-1、AMiner-2 标识；没有直接证据但允许模型先验时，必须写明“模型推理，非知识库直接证据”。"""


GENERAL_QA_RETRIEVAL_TERMS = (
    "enzyme immobilization MOF ZIF carrier support microfluidics droplet "
    "pH temperature Km Michaelis constant mass transfer clogging scale-up cascade catalysis "
    "reusability extreme pH stability enzyme loading activity recovery yield"
)

GENERAL_QA_DOMAIN_RE = re.compile(
    r"("
    r"酶|固定化|包埋|载体|多孔材料|微流控|微液滴|微通道|堵塞|米氏常数|极端酸性|级联催化|"
    r"enzyme|immobili[sz]ation|carrier|support|porous|microfluidic|droplet|channel|clogging|"
    r"michaelis|km|cascade|reusability|extreme\s+ph|"
    r"mof|mofs|zif|zif-8|zif-67|zif-90|uio-66|hkust|cu-btc"
    r")",
    re.I,
)
GENERAL_QA_HARD_OUT_OF_DOMAIN_RE = re.compile(
    r"(天气|股票|红烧肉|胃疼|吃什么药|\breact(?:\.js)?\b|登录页|月亮的诗|"
    r"weather|stock|finance|recipe|medical|medicine|\breact(?:\.js)?\b|poem)",
    re.I,
)


def build_general_qa_retrieval_query(request: GeneralQARequest) -> str:
    parts = [
        request.question,
        request.application_context or "",
        " ".join(request.constraints),
        request.answer_mode,
        GENERAL_QA_RETRIEVAL_TERMS,
    ]
    return " ".join(part for part in parts if part).strip()


def classify_general_qa_guard_query(query: str, plan: Any) -> Optional[str]:
    reason = classify_no_retrieval_query(query, plan)
    if reason == "out_of_domain" and has_general_qa_domain_signal(query) and not GENERAL_QA_HARD_OUT_OF_DOMAIN_RE.search(query):
        return None
    return reason


def has_general_qa_domain_signal(query: str) -> bool:
    return bool(GENERAL_QA_DOMAIN_RE.search(query or ""))


def build_general_qa_guard_query(request: GeneralQARequest) -> str:
    parts = [
        request.question,
        request.application_context or "",
        " ".join(request.constraints),
    ]
    return " ".join(part for part in parts if part).strip()


def build_general_qa_prompt(
    request: GeneralQARequest,
    retrieval: RetrievalResponse,
    external_literature: Optional[ExternalLiteratureResult] = None,
) -> str:
    return "\n\n".join(
        [
            "任务：回答用户在酶固定化、MOF/ZIF 载体、微流控合成、反应条件或性能分析中的通用问题。",
            f"用户问题：{request.question}",
            f"回答模式：{request.answer_mode}",
            f"应用场景：{request.application_context or '未提供'}",
            f"用户约束：{request.constraints or '未提供'}",
            f"允许模型先验：{request.allow_model_prior}",
            "Evidence context:",
            retrieval.context_text(max_chars_per_hit=850) if retrieval.hits else "无可用 evidence context。",
            "External literature context:",
            external_literature_context_text(external_literature),
            "输出策略：",
            "- 简单事实问题：短答 + 证据/推理边界。",
            "- 复杂排障或实验设计：诊断思路、可操作建议、验证实验、风险边界。",
            "- evidence 支持的事实必须带 [1]、[2] reference index。",
            "- AMiner MCP 外部文献只能用 AMiner-1、AMiner-2 标识，且必须说明仍需人工复核。",
            "- evidence 不足但仍回答时，必须把对应段落标为“模型推理，非知识库直接证据”。",
            "- 最近五年/高质量文献类问题必须说明：本地知识库与 AMiner MCP 外部检索都有范围限制。",
            "请输出 JSON object："
            '{"answer":"","evidence_summary":[],"reasoning_notes":[],"limitations":[],"suggested_next_steps":[]}',
        ]
    )


def build_stream_general_qa_prompt(
    request: GeneralQARequest,
    retrieval: RetrievalResponse,
    external_literature: Optional[ExternalLiteratureResult] = None,
) -> str:
    mode_instruction = {
        "direct": "先给 1-2 句直接答案，再补证据边界。",
        "troubleshooting": "按“可能原因 -> 优化动作 -> 验证方式”组织。",
        "literature_review": "按“当前知识库证据 -> AMiner MCP 外部文献线索 -> 文献缺口”组织。",
        "experimental_design": "给 screening matrix / DOE 思路，不给单点必然最优参数。",
    }.get(request.answer_mode, "直接回答问题，并说明证据边界。")
    return "\n\n".join(
        [
            "任务：为前端 live stream 生成通用问答首答。",
            f"用户问题：{request.question}",
            f"回答模式：{request.answer_mode}",
            f"应用场景：{request.application_context or '未提供'}",
            f"用户约束：{request.constraints or '未提供'}",
            f"允许模型先验：{request.allow_model_prior}",
            "Evidence context:",
            retrieval.context_text(max_chars_per_hit=620) if retrieval.hits else "无可用 evidence context。",
            "External literature context:",
            external_literature_context_text(external_literature, max_chars_per_item=480),
            "输出要求：",
            f"- {mode_instruction}",
            "- 有 evidence 支持的关键事实必须带 [1]、[2] reference index。",
            "- AMiner MCP 外部文献只能用 AMiner-1、AMiner-2 标识，不要伪装成本地知识库直接证据。",
            "- 如果 evidence context 不足但仍属于领域问题且允许模型先验，必须写“模型推理，非知识库直接证据”。",
            "- 不要宣称全局最优、唯一最佳、保证成功或 100% 结论。",
            "- 最近五年/高质量文献类问题要说明检索范围限制与人工复核边界。",
            "- 不输出 JSON。",
        ]
    )


def build_answer_payload(
    generation_json: Optional[Dict[str, Any]],
    request: GeneralQARequest,
    retrieval: RetrievalResponse,
    generation: GenerationResponse,
    external_literature: Optional[ExternalLiteratureResult] = None,
) -> Dict[str, Any]:
    if generation_json and isinstance(generation_json.get("answer"), str) and generation_json["answer"].strip():
        return {
            "answer": ensure_answer_boundary(generation_json["answer"].strip(), request, retrieval),
            "evidence_summary": general_qa_evidence_summaries(retrieval, external_literature),
            "reasoning_notes": ensure_reasoning_boundary(
                append_external_literature_notes(string_list(generation_json.get("reasoning_notes")), external_literature),
                request,
                retrieval,
            ),
            "limitations": ensure_limitations(
                string_list(generation_json.get("limitations")),
                request,
                retrieval,
                external_literature,
            ),
            "suggested_next_steps": string_list(generation_json.get("suggested_next_steps")),
        }

    if retrieval_guard_reason(retrieval):
        return {
            "answer": generation.content or build_no_answer_text(),
            "evidence_summary": [],
            "reasoning_notes": [],
            "limitations": ["该请求被 answerability guard 拦截，未进入知识库检索生成。"],
            "suggested_next_steps": [],
        }

    if plain_generation_is_usable(generation):
        return {
            "answer": ensure_answer_boundary(generation.content.strip(), request, retrieval),
            "evidence_summary": general_qa_evidence_summaries(retrieval, external_literature),
            "reasoning_notes": ensure_reasoning_boundary(
                append_external_literature_notes([], external_literature),
                request,
                retrieval,
            ),
            "limitations": ensure_limitations([], request, retrieval, external_literature),
            "suggested_next_steps": suggested_steps_for_mode(request.answer_mode, has_evidence=bool(retrieval.hits)),
        }

    if retrieval.hits:
        grounded = build_grounded_answer(request.question, retrieval) or build_no_answer_text()
        return {
            "answer": grounded,
            "evidence_summary": general_qa_evidence_summaries(retrieval, external_literature),
            "reasoning_notes": append_external_literature_notes(
                ["仅基于当前知识库 evidence 组织回答，未补写未命中的实验事实。"],
                external_literature,
            ),
            "limitations": ensure_limitations([], request, retrieval, external_literature),
            "suggested_next_steps": suggested_steps_for_mode(request.answer_mode, has_evidence=True),
        }

    if request.allow_model_prior:
        answer = model_prior_answer(request)
        return {
            "answer": answer,
            "evidence_summary": general_qa_evidence_summaries(retrieval, external_literature),
            "reasoning_notes": append_external_literature_notes(["模型推理，非知识库直接证据。"], external_literature),
            "limitations": ensure_limitations([], request, retrieval, external_literature),
            "suggested_next_steps": suggested_steps_for_mode(request.answer_mode, has_evidence=False),
        }

    return {
        "answer": build_no_answer_text(),
        "evidence_summary": [],
        "reasoning_notes": [],
        "limitations": ["用户关闭了模型先验，且当前知识库没有检索到可用于回答该问题的可靠 evidence。"],
        "suggested_next_steps": [],
    }


def plain_generation_is_usable(generation: GenerationResponse) -> bool:
    if generation.provider in {"mock", "general_qa_guard", "retrieval_guard"}:
        return False
    return bool(generation.content.strip())


def ensure_answer_boundary(answer: str, request: GeneralQARequest, retrieval: RetrievalResponse) -> str:
    boundary = "模型推理，非知识库直接证据"
    if retrieval.hits or not request.allow_model_prior or boundary in answer:
        return answer
    return f"{boundary}：{answer}"


def string_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def ensure_reasoning_boundary(notes: List[str], request: GeneralQARequest, retrieval: RetrievalResponse) -> List[str]:
    if retrieval.hits or not request.allow_model_prior:
        return notes
    boundary = "模型推理，非知识库直接证据。"
    if not any(boundary in item for item in notes):
        return [*notes, boundary]
    return notes


def should_use_external_literature(request: GeneralQARequest) -> bool:
    text = " ".join(
        [
            request.question,
            request.application_context or "",
            " ".join(request.constraints),
            request.answer_mode,
        ]
    ).lower()
    return request.answer_mode == "literature_review" or bool(
        re.search(
            r"最近\s*五\s*年|近\s*5\s*年|文献|综述|高质量|论文|paper|literature|review|recent|last\s+5\s+years",
            text,
            re.I,
        )
    )


def build_external_literature_query(request: GeneralQARequest) -> str:
    parts = [
        request.question,
        request.application_context or "",
        " ".join(request.constraints),
        "enzyme immobilization MOF ZIF microfluidics lipase",
    ]
    return re.sub(r"\s+", " ", " ".join(part for part in parts if part)).strip()


def external_literature_context_text(
    external_literature: Optional[ExternalLiteratureResult],
    max_chars_per_item: int = 700,
) -> str:
    if external_literature is None:
        return "未启用或未触发 AMiner MCP 外部文献检索。"
    return external_literature.context_text(max_chars_per_item=max_chars_per_item)


def append_external_literature_summaries(
    summaries: List[str],
    external_literature: Optional[ExternalLiteratureResult],
) -> List[str]:
    if external_literature is None or external_literature.status != "success" or not external_literature.items:
        return summaries
    prefix = "AMiner MCP: "
    return dedupe_strings([*summaries, *[f"{prefix}{item}" for item in external_literature.summaries()]])


def general_qa_evidence_summaries(
    retrieval: RetrievalResponse,
    external_literature: Optional[ExternalLiteratureResult],
) -> List[str]:
    return append_external_literature_summaries(evidence_summaries(retrieval), external_literature)


def append_external_literature_notes(
    notes: List[str],
    external_literature: Optional[ExternalLiteratureResult],
) -> List[str]:
    if external_literature is None:
        return notes
    if external_literature.status == "success":
        return dedupe_strings(
            [
                *notes,
                "已接入 AMiner MCP 外部文献检索；这些结果不是本地知识库直接证据，需人工复核检索式、年份、期刊质量和全文结论。",
            ]
        )
    return dedupe_strings([*notes, f"AMiner MCP 外部文献检索未形成可用结果：{external_literature.message or external_literature.status}。"])


def ensure_limitations(
    limitations: List[str],
    request: GeneralQARequest,
    retrieval: RetrievalResponse,
    external_literature: Optional[ExternalLiteratureResult] = None,
) -> List[str]:
    values = list(limitations)
    if not retrieval.hits:
        values.append("当前知识库没有检索到直接 evidence；回答中的推理不能替代文献证据或实验验证。")
    if asks_recent_literature(request.question):
        if external_literature and external_literature.status == "success":
            values.append("最近五年/高质量文献问题已补充 AMiner MCP 外部检索线索，但仍需人工复核检索式、年份、期刊质量和全文结论。")
        else:
            values.append("最近五年/高质量文献问题需要外部检索复核；当前 AMiner MCP 外部检索未命中或不可用。")
    if external_literature and external_literature.status not in {"success", "empty"}:
        values.append(f"AMiner MCP 外部检索不可用：{external_literature.message or external_literature.status}。")
    values.append("不得将本回答理解为全局最优或唯一最佳方案，参数需绑定具体酶、载体、体系和评价指标。")
    return dedupe_strings(values)


def evidence_summaries(retrieval: RetrievalResponse) -> List[str]:
    summaries = []
    for index, hit in enumerate(retrieval.hits[:4], start=1):
        label = hit.citation or hit.source_id or f"hit {index}"
        record_type = hit.record_type or hit.point_type
        text = re.sub(r"\s+", " ", (hit.text or hit.source_chunk_text or "").strip())[:180]
        summaries.append(f"[{index}] {label} / {record_type}: {text}")
    return summaries


def model_prior_answer(request: GeneralQARequest) -> str:
    lead = "模型推理，非知识库直接证据：当前知识库没有命中直接 evidence。"
    if request.answer_mode == "troubleshooting":
        return "\n".join(
            [
                lead,
                "优先从成核/沉淀速率、前驱体浓度、两相流稳定性、通道润湿性、颗粒聚集和 residence time 六个方向排查。",
                "工程上先做小范围 DOE：降低 MOF 前驱体局部过饱和、提高分散相剪切稳定性、缩短通道内成核前停留时间，并用显微观察确认堵塞发生在入口、混合段还是收集端。",
            ]
        )
    if request.answer_mode == "literature_review":
        return "\n".join(
            [
                lead,
                "可以先用关键词组合检索：enzyme immobilization、droplet microfluidics、MOF/ZIF、in situ encapsulation、mass transfer、reusability。",
                "当前回答不能声称覆盖最近五年高质量文献；需要外部数据库检索后再做系统综述。",
            ]
        )
    if request.answer_mode == "experimental_design":
        return "\n".join(
            [
                lead,
                "推荐把变量拆成载体组成、pH/温度、enzyme loading、交联/表面活性剂、反应/assay 条件五组，使用 fractional factorial 或小型 DOE 找交互项。",
                "输出应是可验证 screening matrix，而不是单点“最优条件”。",
            ]
        )
    return (
        f"{lead}\n"
        "可以给出领域内的 starting point，但必须通过同酶、同载体、同底物体系的对照实验验证，不能写成普适最优结论。"
    )


def suggested_steps_for_mode(answer_mode: GeneralQAAnswerMode, has_evidence: bool) -> List[str]:
    if answer_mode == "troubleshooting":
        return [
            "记录堵塞位置、粒径分布、压降变化和两相流型，先定位堵塞机制。",
            "围绕浓度、流速比、表面活性剂和 residence time 做小范围 DOE。",
        ]
    if answer_mode == "literature_review":
        return [
            "先用本地 evidence 生成候选关键词，再到外部数据库检索最近五年文献。",
            "按载体类型、固定化方法、性能指标和循环稳定性分层整理。",
        ]
    if answer_mode == "experimental_design":
        return [
            "把变量拆成可控因子和评价指标，优先做小规模 factorial screening。",
            "保留游离酶、空载体、无酶 MOF 和重复循环对照。",
        ]
    if has_evidence:
        return ["回到引用文献确认实验体系，再设计同条件对照。"]
    return ["补充目标酶、载体、反应体系和评价指标后重新检索。"]


def deterministic_general_no_answer_generation(reason: str) -> GenerationResponse:
    return GenerationResponse(
        provider="general_qa_guard",
        model="deterministic-no-answer-v1",
        content=f"证据不足：{reason}。该请求没有足够相关的酶固定化/MOF/微流控 evidence，不能生成通用问答结论。",
        finish_reason="guarded",
        usage={"guarded": True, "retrieval_guard": reason},
    )


def asks_recent_literature(question: str) -> bool:
    text = (question or "").lower()
    return bool(
        re.search(r"最近\s*五\s*年|近\s*5\s*年|recent\s+five\s+years|last\s+5\s+years|high[- ]quality", text)
        or ("文献" in question and any(term in question for term in ["最近", "近五年", "系统", "综述"]))
    )


def make_general_qa_id(request: GeneralQARequest, retrieval: RetrievalResponse) -> str:
    digest = hashlib.sha1(
        "\n".join(
            [
                request.question,
                request.answer_mode,
                build_general_qa_retrieval_query(request),
                ",".join(hit.source_id for hit in retrieval.hits[:5]),
            ]
        ).encode("utf-8")
    ).hexdigest()[:16]
    return f"gqa_{digest}"


def dedupe_strings(values: List[str]) -> List[str]:
    seen = set()
    deduped = []
    for value in values:
        key = value.strip()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(key)
    return deduped
