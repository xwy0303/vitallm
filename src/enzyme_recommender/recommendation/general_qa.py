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
from enzyme_recommender.recommendation.grounding import (
    asks_condition_type,
    build_no_answer_text,
    facts_from_hits,
    select_answer_hits,
)
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
如果 evidence context 不足但问题仍属于本领域，并且用户允许模型先验，可以给基于通用科学原理的推理；这类内容必须在对应大模块末尾集中标注“模型推理，非知识库直接证据”。
同一个大模块内不要在每一句、每一条 bullet 或每一小段后重复边界声明；最多在该模块末尾写一次证据边界。
不得宣称全局最优、唯一最佳或保证成功；涉及文献时效的问题必须说明检索范围和外部 MCP 结果仍需人工复核。
输出必须是 JSON object。"""


STREAM_SYSTEM_PROMPT = """你是一个面向酶固定化、MOF/ZIF 载体和微流控固定化实验的通用问答助手。
优先快速输出自然中文，不输出 JSON。有本地 evidence context 时关键事实必须带 [1]、[2] reference index；External literature context 只能用 AMiner-1、AMiner-2 标识；没有直接证据但允许模型先验时，必须在对应大模块末尾集中写明“模型推理，非知识库直接证据”。不要在每一句、每一条 bullet 或每一小段后重复该边界声明。"""


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
MODEL_REASONING_MARKER = "模型推理，非知识库直接证据"
MODEL_REASONING_SECTION_NOTE = (
    "证据边界：本模块中未带 citation 的机制解释、排障判断或工程建议属于"
    "模型推理，非知识库直接证据，需用同体系实验验证。"
)
KNOWLEDGE_HIT_PREFIX = "根据知识库命中的切片，"
NO_KNOWLEDGE_HIT_PREFIX = "知识库没有命中直接相关切片，下面是基于大模型领域知识和通用科学原理的回答。"
MARKDOWN_MAJOR_HEADING_RE = re.compile(r"^\s{0,3}#{1,3}\s+\S+")
SOURCE_NOTICE_RE = re.compile(
    r"^(?:"
    r"根据知识库命中的切片[，,]?"
    r"|知识库没有命中直接相关切片，下面是基于大模型领域知识和通用科学原理的回答。"
    r"|知识库里没有，下面是大模型检索的回答[。.]?"
    r")"
)
MODEL_REASONING_MARKER_RE = re.compile(
    r"(?:属于|为|是)?(?:\*\*)?模型推理，非知识库直接证据(?:\*\*)?[：:，,。.\s]*"
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
            general_qa_mode_output_contract(request.answer_mode),
            "- evidence 支持的事实必须带 [1]、[2] reference index。",
            "- AMiner MCP 外部文献只能用 AMiner-1、AMiner-2 标识，且必须说明仍需人工复核。",
            "- evidence 不足但仍回答时，只在对应大模块最后集中写一次“证据边界：本模块中未带 citation 的机制解释、排障判断或工程建议属于模型推理，非知识库直接证据，需用同体系实验验证。”",
            "- 禁止在每一句、每一条 bullet 或每一小段后重复“模型推理，非知识库直接证据”。",
            "- 最近五年/高质量文献类问题必须说明：本地知识库与 AMiner MCP 外部检索都有范围限制。",
            "- answer 第一句必须说明来源：如果有本地 evidence hits，以“根据知识库命中的切片，”开头；如果没有本地 evidence hits，以“知识库没有命中直接相关切片，下面是基于大模型领域知识和通用科学原理的回答。”开头。若 answer 以 markdown 标题开头，来源句放在第一个标题下面，不要把来源句和标题写在同一行。",
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
        "direct": "按“### 结论 -> ### 证据边界 -> ### 建议下一步”组织；结论 2-3 句，证据边界 2-4 条，不要只输出单段短答。",
        "troubleshooting": "按“### 诊断思路 -> ### 可能原因 -> ### 优化动作 -> ### 验证方式与风险边界”组织；保持可能原因 -> 优化动作 -> 验证方式的排障链路。",
        "literature_review": "按“### 当前知识库证据 -> ### AMiner MCP 外部文献线索 -> ### 文献缺口与复核边界”组织。",
        "experimental_design": "按“### 设计原则 -> ### Screening matrix / DOE -> ### 验证指标 -> ### 风险边界”组织；不给单点必然最优参数。",
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
            "- 如果 evidence context 不足但仍属于领域问题且允许模型先验，只在对应大模块最后集中写一次：证据边界：本模块中未带 citation 的机制解释、排障判断或工程建议属于模型推理，非知识库直接证据，需用同体系实验验证。",
            "- 禁止在每一句、每一条 bullet 或每一小段后重复“模型推理，非知识库直接证据”。",
            "- 不要宣称全局最优、唯一最佳、保证成功或 100% 结论。",
            "- 最近五年/高质量文献类问题要说明检索范围限制与人工复核边界。",
            "- 第一句必须说明来源：有本地 evidence hits 时，以“根据知识库命中的切片，”开头；没有本地 evidence hits 时，以“知识库没有命中直接相关切片，下面是基于大模型领域知识和通用科学原理的回答。”开头。若回答以 markdown 标题开头，来源句放在第一个标题下面，不要把来源句和标题写在同一行。",
            "- 不输出 JSON。",
        ]
    )


def general_qa_mode_output_contract(answer_mode: GeneralQAAnswerMode) -> str:
    if answer_mode == "troubleshooting":
        return (
            "- 复杂排障问题必须输出 4 个大模块：诊断思路、可能原因、优化动作、验证方式与风险边界；"
            "每个模块给可操作内容，但证据边界只在模块末尾集中出现一次。"
        )
    if answer_mode == "literature_review":
        return (
            "- 文献/综述问题必须输出 3 个大模块：当前知识库证据、AMiner MCP 外部文献线索、文献缺口与复核边界；"
            "不得把外部检索线索写成知识库直接证据。"
        )
    if answer_mode == "experimental_design":
        return (
            "- 实验设计问题必须输出 4 个大模块：设计原则、screening matrix / DOE、验证指标、风险边界；"
            "给参数范围和对照矩阵，不给单点必然最优参数。"
        )
    return (
        "- 简单事实问题也必须输出稳定最小结构：结论、证据边界、建议下一步；"
        "结论保持简洁，但不要只输出一段短答。"
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
            "answer": ensure_answer_boundary(
                ensure_knowledge_source_prefix(
                    normalize_model_reasoning_markers(generation_json["answer"].strip()),
                    retrieval,
                ),
                request,
                retrieval,
            ),
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
            "answer": ensure_answer_boundary(
                ensure_knowledge_source_prefix(
                    normalize_model_reasoning_markers(generation.content.strip()),
                    retrieval,
                ),
                request,
                retrieval,
            ),
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
        grounded = build_mode_aware_grounded_fallback_answer(request, retrieval) or build_no_answer_text()
        return {
            "answer": ensure_knowledge_source_prefix(grounded, retrieval),
            "evidence_summary": general_qa_evidence_summaries(retrieval, external_literature),
            "reasoning_notes": append_external_literature_notes(
                ["LLM 生成不可用时已降级为 mode-aware 知识库摘要；未补写未命中的实验事实。"],
                external_literature,
            ),
            "limitations": ensure_limitations([], request, retrieval, external_literature),
            "suggested_next_steps": suggested_steps_for_mode(request.answer_mode, has_evidence=True),
        }

    if request.allow_model_prior:
        answer = ensure_answer_boundary(
            ensure_knowledge_source_prefix(model_prior_answer(request), retrieval),
            request,
            retrieval,
        )
        return {
            "answer": answer,
            "evidence_summary": general_qa_evidence_summaries(retrieval, external_literature),
            "reasoning_notes": append_external_literature_notes(["模型推理，非知识库直接证据。"], external_literature),
            "limitations": ensure_limitations([], request, retrieval, external_literature),
            "suggested_next_steps": suggested_steps_for_mode(request.answer_mode, has_evidence=False),
        }

    return {
        "answer": ensure_knowledge_source_prefix(build_no_answer_text(), retrieval),
        "evidence_summary": [],
        "reasoning_notes": [],
        "limitations": ["用户关闭了模型先验，且当前知识库没有检索到可用于回答该问题的可靠 evidence。"],
        "suggested_next_steps": [],
    }


def build_mode_aware_grounded_fallback_answer(request: GeneralQARequest, retrieval: RetrievalResponse) -> str:
    fact_lines = fallback_fact_lines(request, retrieval)
    if request.answer_mode == "troubleshooting":
        return "\n".join(
            [
                "### 诊断思路",
                "当前 LLM 生成不可用，以下为基于知识库命中切片组织的降级回答。先把现象拆成材料稳定性、酶构象稳定性、传质阻力和操作条件四类，不直接给单点最优结论。",
                "",
                "### 可能原因",
                *fact_lines,
                "- 若命中证据只覆盖固定化条件或稳定性测试，不能直接推出实际反应故障的唯一原因。",
                "",
                "### 优化动作",
                "- 优先保留游离酶、空载体、固定化酶三组对照，逐一改变 pH、温度、离子强度和底物浓度。",
                "- 对 MOF/ZIF 体系，先确认载体在目标 pH 或溶剂环境下是否结构保持，再讨论酶保护效果。",
                "",
                "### 验证方式与风险边界",
                "- 用残余活性、蛋白泄漏、粒径/形貌、XRD/FTIR 或孔结构表征验证失活来源。",
                "证据边界：本模块中未带 citation 的机制解释、排障判断或工程建议属于模型推理，非知识库直接证据，需用同体系实验验证。",
            ]
        )
    if request.answer_mode == "literature_review":
        return "\n".join(
            [
                "### 当前知识库证据",
                "当前 LLM 生成不可用，以下先给知识库命中切片摘要，不把它写成系统综述结论。",
                *fact_lines,
                "",
                "### AMiner MCP 外部文献线索",
                "- 本降级回答未展开外部文献归纳；若问题要求最近五年或高质量文献，需要后续外部检索复核。",
                "",
                "### 文献缺口与复核边界",
                "- 需要按同一种酶、同一种载体、固定化方法、assay 条件和性能指标重新分层比较。",
                "- 当前命中切片只能作为候选证据，不能替代全文级文献筛选。",
            ]
        )
    if request.answer_mode == "experimental_design":
        return "\n".join(
            [
                "### 设计原则",
                "当前 LLM 生成不可用，以下为基于知识库命中切片组织的降级实验设计。先把已命中事实作为约束，再用小规模 DOE 验证未命中的条件空间。",
                *fact_lines,
                "",
                "### Screening matrix / DOE",
                "- 因子建议：载体类型或改性方式、固定化方法、pH 梯度、温度梯度、酶/载体比例、反应或孵育时间。",
                "- 每个因子先取 2-3 个水平做 screening，不直接押注单点最优参数。",
                "- 必设对照：游离酶、空载体、无酶 MOF/ZIF、固定化后洗脱液蛋白检测。",
                "",
                "### 验证指标",
                "- 初始活性、残余活性、activity recovery、循环使用次数、蛋白泄漏、载体结构完整性和传质相关指标。",
                "",
                "### 风险边界",
                "- 命中切片若来自固定化条件，不能直接等同于最佳催化反应条件；若来自热/酸稳定性测试，也不能直接等同于最适反应条件。",
                "证据边界：本模块中未带 citation 的机制解释、排障判断或工程建议属于模型推理，非知识库直接证据，需用同体系实验验证。",
            ]
        )
    condition_warning = (
        "- 需要区分固定化条件、assay 条件和反应/application 条件；不同实验环节的 pH/温度不能合并为一个跨体系结论。"
        if asks_condition_type(request.question)
        else "- 当前命中切片只支持局部事实，不能外推为跨体系通用结论。"
    )
    return "\n".join(
        [
            "### 结论",
            "当前 LLM 生成不可用，以下为基于知识库命中切片组织的降级回答。可以先确认已命中的实验事实，但不能给出全局最佳或唯一最优结论。",
            "",
            "### 证据边界",
            *fact_lines,
            condition_warning,
            "- 本回答只基于已检索 evidence 组织，未补写未命中的实验事实。",
            "",
            "### 建议下一步",
            "- 打开引用切片对应原文，确认命中参数属于固定化、assay、稳定性测试还是实际应用反应。",
            "- 若需要确定最佳参数，按同一酶、同一载体、同一底物体系设计小范围梯度实验。",
        ]
    )


def fallback_fact_lines(request: GeneralQARequest, retrieval: RetrievalResponse) -> List[str]:
    selected = select_answer_hits(request.question, retrieval, limit=4)
    facts = facts_from_hits(selected, retrieval)
    if not facts:
        return ["- 当前命中 evidence 没有可稳定抽取的结构化字段，需打开引用切片复核。"]
    return [f"- {fact['text']} [{fact['ref']}]" for fact in facts[:5]]


def plain_generation_is_usable(generation: GenerationResponse) -> bool:
    if generation.provider in {"mock", "general_qa_guard", "retrieval_guard"}:
        return False
    return bool(generation.content.strip())


def ensure_answer_boundary(answer: str, request: GeneralQARequest, retrieval: RetrievalResponse) -> str:
    if retrieval.hits or not request.allow_model_prior or MODEL_REASONING_MARKER in answer:
        return answer
    return append_model_reasoning_note(answer)


def ensure_knowledge_source_prefix(answer: str, retrieval: RetrievalResponse) -> str:
    body = answer.strip()
    if not body:
        return body
    prefix = KNOWLEDGE_HIT_PREFIX if retrieval.hits else NO_KNOWLEDGE_HIT_PREFIX

    stripped_body = body.lstrip()
    leading_notice = SOURCE_NOTICE_RE.match(stripped_body)
    if leading_notice:
        rest = stripped_body[leading_notice.end() :].lstrip()
        if MARKDOWN_MAJOR_HEADING_RE.match(rest):
            return ensure_knowledge_source_prefix(rest, retrieval)
        if stripped_body.startswith(prefix):
            return body
        return join_source_notice(prefix, rest)

    lines = body.splitlines()
    if lines and MARKDOWN_MAJOR_HEADING_RE.match(lines[0]):
        return insert_source_notice_after_first_heading(lines, prefix)

    return join_source_notice(prefix, body)


def insert_source_notice_after_first_heading(lines: List[str], prefix: str) -> str:
    insert_at = 1
    while insert_at < len(lines) and not lines[insert_at].strip():
        insert_at += 1

    if insert_at >= len(lines):
        return collapse_blank_lines("\n".join([*lines, "", source_notice_sentence(prefix)]).strip())

    current_line = lines[insert_at]
    stripped_line = current_line.lstrip()
    line_notice = SOURCE_NOTICE_RE.match(stripped_line)
    if line_notice:
        rest = stripped_line[line_notice.end() :].lstrip()
        replacement = source_notice_with_optional_rest(prefix, rest)
        lines[insert_at : insert_at + 1] = replacement
        return collapse_blank_lines("\n".join(lines).strip())

    if can_attach_source_prefix(current_line, prefix):
        indent = current_line[: len(current_line) - len(stripped_line)]
        lines[insert_at] = f"{indent}{prefix}{stripped_line}"
        return collapse_blank_lines("\n".join(lines).strip())

    lines[insert_at:insert_at] = [source_notice_sentence(prefix), ""]
    return collapse_blank_lines("\n".join(lines).strip())


def join_source_notice(prefix: str, body: str) -> str:
    if not body:
        return source_notice_sentence(prefix)
    if prefix == NO_KNOWLEDGE_HIT_PREFIX:
        return f"{prefix}\n\n{body}"
    return f"{prefix}{body}"


def source_notice_with_optional_rest(prefix: str, rest: str) -> List[str]:
    if not rest:
        return [source_notice_sentence(prefix)]
    if prefix == NO_KNOWLEDGE_HIT_PREFIX:
        return [prefix, "", rest]
    return [f"{prefix}{rest}"]


def source_notice_sentence(prefix: str) -> str:
    if prefix == NO_KNOWLEDGE_HIT_PREFIX:
        return prefix
    return f"{prefix}以下回答优先基于已检索 evidence，并在证据不足处标注推理边界。"


def can_attach_source_prefix(line: str, prefix: str) -> bool:
    if prefix == NO_KNOWLEDGE_HIT_PREFIX:
        return False
    stripped = line.lstrip()
    return not (
        MARKDOWN_MAJOR_HEADING_RE.match(stripped)
        or stripped.startswith(("-", "*", "+", "|", "```"))
    )


def normalize_model_reasoning_markers(answer: str) -> str:
    if MODEL_REASONING_MARKER not in answer:
        return answer

    normalized_lines: List[str] = []
    section_has_marker = False
    saw_marker = False

    def flush_section_note() -> bool:
        nonlocal section_has_marker
        if not section_has_marker:
            return False
        trim_trailing_blank_lines(normalized_lines)
        if normalized_lines:
            normalized_lines.append("")
        normalized_lines.append(MODEL_REASONING_SECTION_NOTE)
        section_has_marker = False
        return True

    for raw_line in answer.splitlines():
        if MARKDOWN_MAJOR_HEADING_RE.match(raw_line) and normalized_lines:
            if flush_section_note():
                normalized_lines.append("")
        if MODEL_REASONING_MARKER in raw_line:
            saw_marker = True
            section_has_marker = True
            cleaned = MODEL_REASONING_MARKER_RE.sub("", raw_line).strip()
            if cleaned and not is_redundant_model_boundary_line(cleaned):
                normalized_lines.append(cleaned)
            continue
        normalized_lines.append(raw_line)

    flush_section_note()
    if not saw_marker:
        return answer
    return collapse_blank_lines("\n".join(normalized_lines).strip())


def append_model_reasoning_note(answer: str) -> str:
    body = answer.strip()
    if not body:
        return MODEL_REASONING_SECTION_NOTE
    return f"{body}\n\n{MODEL_REASONING_SECTION_NOTE}"


def is_redundant_model_boundary_line(line: str) -> bool:
    stripped = line.strip().lstrip("-").strip().strip("*").strip()
    return stripped.startswith("证据边界") and "同体系实验验证" in stripped


def trim_trailing_blank_lines(lines: List[str]) -> None:
    while lines and not lines[-1].strip():
        lines.pop()


def collapse_blank_lines(value: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", value)


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
    if request.answer_mode == "troubleshooting":
        return "\n".join(
            [
                "优先从成核/沉淀速率、前驱体浓度、两相流稳定性、通道润湿性、颗粒聚集和 residence time 六个方向排查。",
                "工程上先做小范围 DOE：降低 MOF 前驱体局部过饱和、提高分散相剪切稳定性、缩短通道内成核前停留时间，并用显微观察确认堵塞发生在入口、混合段还是收集端。",
            ]
        )
    if request.answer_mode == "literature_review":
        return "\n".join(
            [
                "可以先用关键词组合检索：enzyme immobilization、droplet microfluidics、MOF/ZIF、in situ encapsulation、mass transfer、reusability。",
                "当前回答不能声称覆盖最近五年高质量文献；需要外部数据库检索后再做系统综述。",
            ]
        )
    if request.answer_mode == "experimental_design":
        return "\n".join(
            [
                "推荐把变量拆成载体组成、pH/温度、enzyme loading、交联/表面活性剂、反应/assay 条件五组，使用 fractional factorial 或小型 DOE 找交互项。",
                "输出应是可验证 screening matrix，而不是单点“最优条件”。",
            ]
        )
    return (
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
