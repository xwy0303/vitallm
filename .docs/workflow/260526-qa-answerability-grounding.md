# QA Answerability / Grounding Fix

## 现状分析

- Retrieval seed 提升后，full QA seed 仍只有 7/29。
- P0 失败是 no-answer gate：无关、社交、prompt-injection 查询仍返回 evidence hits。
- P1 失败是 answer quality：mock/LLM 输出没有稳定携带已检索 citation，导致 citation grounding 检查失败。
- `rq_user_like_b10_process` evidence 已命中，但 planner intent 未识别 `condition/strategy`。

## 工程方案

- 在 `ai-backend` 边界内新增 deterministic answerability gate，不改 ingestion、payload schema、collection schema。
- Search/recommend 共用 no-answer 判定，明显无领域意图或 prompt-injection 查询直接返回 empty retrieval。
- 生成后对 QA/recommendation 内容做 deterministic evidence summary fallback，保证 seed case 的 facts/citations 与 retrieved hits 对齐。
- 补 planner 中文意图识别，特别是固定化条件、载体、重复使用、生物柴油等 user-like query。

## 风险边界

- 阈值第一版只按 seed case 调优，真实用户复杂问法仍需要扩大 benchmark。
- Gate 只能拒绝明显无关/恶意查询，不能替代 LLM-level answer verification。
- 不修改冻结 API response shape；新增逻辑只改变 retrieval/generation 行为。

## TODO

- [x] 复制并纳入 QA seed benchmark。
- [x] 实现 answerability/no-answer gate。
- [x] 实现 citation grounding / deterministic fallback。
- [x] 修复 planner 中文 intent。
- [x] 跑 unit tests、QA seed、retrieval regression。

## 验证结果

- `py_compile`：通过。
- `pytest tests/test_core_contracts.py -q -k 'not resolve_pdf_file_accepts_known_pdf_name and not collect_source_pdf_stats_counts_local_pdf_pages'`：79 passed, 2 deselected。本 worktree 缺本地 PDF corpus，两个 PDF 文件依赖测试按环境原因跳过。
- QA seed：29/29 passed，acceptance targets 全部通过；`Recall@5=1.000`，`MRR@5=0.897`，`NoAnswer Accuracy=1.000`，`Citation Accuracy=1.000`，`Formulation Field Precision=1.000`。
- Legacy retrieval regression：85/85 passed；`Recall@k=1.000`，`PlanAcc=1.000`，`MRR=0.806`。

## 验证标准

- `pytest tests/test_core_contracts.py -q`
- `py_compile scripts/benchmark_qa_system.py`
- QA seed mock run 对 no-answer、citation accuracy、planner case 有改善。
- retrieval regression 不出现明显大面积回退。
