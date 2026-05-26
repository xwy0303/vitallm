# QA Benchmark Strategy

## 定位

`benchmarks/retrieval_smoke.json` 已降级为 62 条 legacy retrieval regression gate，只用于 collection、schema、rerank 回归，不代表端到端问答质量。

新的分层 QA benchmark 以 `scripts/benchmark_qa_system.py` 为统一 runner，覆盖 retrieval、answer quality、no-answer、formulation optimizer、citation、unsupported claim 和 stream/final consistency。

## Benchmark Manifests

v1 目标总量为 220 条 curated case，当前先落 seed set，不伪装成完整统计 benchmark：

- `benchmarks/retrieval_quality_v1.json`：目标 120 条，当前 10 条。
- `benchmarks/answer_quality_v1.json`：目标 50 条，当前 5 条。
- `benchmarks/no_answer_intent_v1.json`：目标 30 条，当前 10 条。
- `benchmarks/formulation_optimizer_v1.json`：目标 20 条，当前 4 条。

manifest schema artifact：

```text
schemas/generated/qa_benchmark_manifest.schema.json
```

runner 还会做 JSON Schema 之外的语义校验：no-answer 必须断言 no candidates / no citations / no next experiment，`literature_derived` 必须标记 `literature_rewrite=true`，positive/answer/formulation case 必须绑定 expected evidence。

## 常用命令

只校验 manifests，不加载 Qdrant / embedding / LLM：

```bash
.venv/bin/python scripts/benchmark_qa_system.py \
  --validate-only \
  --output artifacts/benchmarks/qa_manifest_validation_20260526.json \
  --markdown reports/qa_manifest_validation_20260526.md
```

跑完整 seed suite，默认 mock generation，不依赖 paid LLM judge：

```bash
.venv/bin/python scripts/benchmark_qa_system.py \
  --generation-mode mock \
  --allow-failures \
  --output artifacts/benchmarks/qa_system_seed_20260526.json \
  --markdown reports/qa_system_seed_20260526.md
```

跑 retrieval-only seed：

```bash
.venv/bin/python scripts/benchmark_qa_system.py \
  --benchmark benchmarks/retrieval_quality_v1.json \
  --generation-mode skip \
  --allow-failures \
  --output artifacts/benchmarks/qa_retrieval_quality_seed_20260526.json \
  --markdown reports/qa_retrieval_quality_seed_20260526.md
```

注意：在 Codex sandbox 中，Python/httpx 访问本机 Qdrant `127.0.0.1:6333` 可能需要权限提升；这不是 Qdrant collection 本身不可用。

## v1 Acceptance Targets

- Retrieval：`Recall@5 >= 0.95`，`MRR@5 >= 0.85`，`Forbidden Hit Rate = 0`。
- No-answer：`NoAnswer Accuracy = 1.00`，`Unexpected Candidate Rate = 0`，`Unexpected Citation Rate = 0`。
- Answer quality：`Citation Accuracy >= 0.90`，`Unsupported Claim Count <= 0.10 / answer`，`Condition Type Accuracy >= 0.90`。
- Stream/final：`Stream/Final Consistency >= 0.98`，不允许 stream 说证据不足而 final 生成推荐。
- Formulation：`Evidence-backed Change Rate >= 0.90`，不允许宣称“全局最优”。

## Seed Baseline 260526

完整 seed suite：

```text
artifacts/benchmarks/qa_system_seed_20260526.json
reports/qa_system_seed_20260526.md
```

结果：

- Passed：9/29，pass rate 0.310。
- Retrieval：17 cases，Recall@5 0.647，MRR@5 0.608，nDCG@5 0.613，plan_accuracy 0.828。
- No-answer：10 cases，NoAnswer Accuracy 0.000，False Retrieval Rate 1.000，Unexpected Candidate Rate 0.800，Unexpected Citation Rate 0.800。
- Answer quality：5 cases，Citation Accuracy 1.000，Answer Relevancy 0.800，Unsupported Claim Count 0.000 / answer。
- Formulation：4 cases，Field Recommendation Precision 0.000，Evidence-backed Change Rate 0.750。

主要失败模式：

- 中文口语化 / 中英混合 query 的 planner 与 retrieval routing 不稳，BCL/ZIF-8 用户问题容易跑到非 B10 文档。
- no-answer gate 缺失，`abc`、`不知道`、`你好`、`我爱你`、跨领域和 prompt injection 均会进入 RAG 召回。
- `recommend_stream` 可见文本与 final structured candidates 存在污染风险。
- formulation optimizer 对 BCL-ZIF-8 条件字段级建议不稳定，table row 容易压过 formulation_condition。

## 扩展原则

- v1 扩到 220 条后再将完整 suite 作为稳定统计 benchmark；当前 seed 只作为工程回归与失败模式暴露工具。
- 至少 40% case 应来自 `manual_user_like`、模糊、口语化、非原文表达。
- 跨文档比较 case 至少绑定 2 条 expected evidence。
- LLM judge 只能作为 P1 增强；deterministic checks 与人工 gold facts 优先。
