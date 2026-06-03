# 通用问答模块开发

## 现状分析

- 首页已有“通用问答”前端模式，但后端仍复用 `/api/recommend/by-enzyme` 与 `answer_evidence_question` objective，容易与推荐候选、配方优化和论文问答串味。
- 配方优化已有成熟的 evidence-first 检索、prompt、stream/final 与 deterministic fallback 模式，可作为通用问答的工程骨架参考。
- 原有 no-answer guard 偏脂肪酶固定化推荐场景，直接拼检索增强词会让低信息输入绕过 guard，因此通用问答必须先基于原始问题做 answerability 判断。

## 工程方案

- 新增 `GeneralQAService`，并行于 `RecommendationService` 和 `FormulationOptimizationService`。
- 新增 `/api/qa/general` 与 `/api/qa/general/stream`，前端 `general` mode 迁移到新 endpoint。
- 通用问答 response 固定包含 `answer`、`evidence_summary`、`reasoning_notes`、`limitations`、`suggested_next_steps`、`evidence_hits`。
- 有 evidence 时优先引用；无 evidence 但属于酶固定化/MOF/微流控/Km/传质等领域且允许模型先验时，必须标注“模型推理，非知识库直接证据”。
- 新增 `benchmarks/general_qa_v1.json` 25 条用例，并将 benchmark runner/schema 纳入 `general_qa` 和 `general_qa_stream`。

## 风险与边界

- v1 不接实时外部文献检索；最近五年/高质量文献类问题只能说明本地知识库范围限制。
- 通用问答放宽领域边界，但仍拦截 prompt injection、低信息输入和明显跨领域问题。
- 不修改既有 recommendation/formulation response shape，避免破坏旧接口和已有 benchmark。

## TODO

- [x] 新增后端 service、API schema 和 stream endpoint。
- [x] 前端通用问答模式迁移到 `/api/qa/general/stream`。
- [x] 扩展 benchmark runner、manifest schema 和 25 条通用问答案例。
- [x] 增加 prompt、guard、fallback 和 stream contract 单元测试。
- [x] 运行 py_compile、manifest validation 和目标单元测试。
- [ ] 等 Haien 验收后移动到 `.docs/workflow/done/` 并从活跃任务池移除。

## 验证标准

- `.venv/bin/python -m py_compile src/enzyme_recommender/recommendation/general_qa.py src/enzyme_recommender/api/models.py src/enzyme_recommender/api/app.py scripts/benchmark_qa_system.py`
- `.venv/bin/python scripts/benchmark_qa_system.py --validate-only --json`
- `.venv/bin/python -m pytest tests/test_core_contracts.py -q -k 'general_qa or manifest_validation_summary or layered_manifests or formal_manifest_schema or LiveStreamPromptTests'`

## 验证结果

- `py_compile`：通过。
- `node --check web/app.js`：通过。
- `tests/test_core_contracts.py`：106 passed。
- 通用问答 benchmark manifest：25/25 validate-only 通过。
- 默认 5 个 benchmark manifest：257/257 validate-only 通过。
- `benchmarks/general_qa_v1.json` mock run：25/25 passed，`citation_accuracy=1.0`，`unsupported_claim_count_per_answer=0.0`，`condition_type_accuracy=1.0`，`stream_final_consistency=1.0`。
