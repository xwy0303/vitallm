# RAG Retrieval Architecture

## 当前目标

MVP 阶段先建立可复跑的本地 retrieval 闭环：

```text
MinerU artifact -> RAG inputs -> evidence records -> vector points -> retrieval smoke test
```

当前不是最终科学检索模型。第一目标是把 evidence traceability、metadata filter、quality flags 和 ranking 禁用边界打穿。

## Collection 设计

当前 live Qdrant collection：

```text
enzyme_immobilization_literature_sentence_baai_bge_base_en_v1_5_768_point_schema_v1
```

hash rollback baseline collection：

```text
enzyme_immobilization_literature
```

历史 B10 rollback collection：

```text
enzyme_immobilization_b10
```

`enzyme_immobilization_literature_sentence_baai_bge_base_en_v1_5_768_point_schema_v1` 是当前 live semantic collection。`enzyme_immobilization_literature` 保留为 hash_v1 rollback baseline。`enzyme_immobilization_b10` 保留了最初 smoke test 语义，只能作为历史对照使用，不能作为新增 PDF ingestion 默认目标。

同一个 collection 存三类 point：

- `rag_chunk`：正文和表格镜像 chunk，用于召回上下文。
- `table_record`：结构化表格，用于表格级召回和调试。
- `evidence_record`：抽取后的候选事实，用于推荐和公式优化的优先召回。

核心 payload 字段：

- `document_id`
- `source_pdf`
- `source_id`
- `point_type`
- `page_start`
- `page_end`
- `section`
- `citation`
- `quality_flags`
- `requires_review`
- `usable_for_ranking`
- `text`

`evidence_record` 额外保留：

- `record_type`
- `parent_source_id`
- `confidence`
- `review_reasons`
- `extracted`
- `metrics`

## Embedding 策略

当前 live API 使用 `BAAI/bge-base-en-v1.5` sentence embedding（768 维，`local_files_only: true`）：

```text
enzyme_immobilization_literature_sentence_baai_bge_base_en_v1_5_768_point_schema_v1
```

hash_v1 baseline 作为 rollback / benchmark collection 保留：

```text
enzyme_immobilization_literature
```

保留双 collection 的原因：

- 当前实现仍可离线加载本地模型缓存，避免外网依赖。
- semantic collection 承担 live API 和默认 ingestion。
- hash collection 保留稳定 rollback 和回归基线。
- embedding 替换不应改变 RAG artifact schema 和 Qdrant payload contract。

边界：

- 切回 hash 时必须显式使用 `configs/local.hash.yaml` 或 collection override；不要把 hash collection 覆盖重建成 semantic vectors。
- 后续仍可评估 BGE-M3、SciBERT/SPECTER 类科学文本 embedding，或领域微调 reranker。

## 本地 Qdrant

当前本地验证使用 Qdrant `v1.18.0` Apple Silicon release：

```text
qdrant-aarch64-apple-darwin.tar.gz
sha256: 1ced2cf6fb637a8184229e2d63f1a096c9f7854ec92bf0f0739f33d4059f9df7
```

二进制和 storage 放在 `.local/qdrant/`，该目录不进入 git。

启动：

```bash
scripts/start_qdrant_local.sh
```

停止：

```bash
scripts/stop_qdrant_local.sh
```

当前 live semantic collection 已创建 retrieval/filter 常用 payload indexes：

- `point_type`
- `record_type`
- `document_id`
- `source_pdf`
- `candidate_source`
- `curation_status`
- `qa_status`
- `usable_for_ranking`
- `requires_review`

初始化或补齐命令：

```bash
PYTHONPATH=src .venv/bin/python scripts/ensure_qdrant_payload_indexes.py \
  --config configs/local.yaml
```

索引单篇文献到当前 live semantic collection：

```bash
PYTHONPATH=src .venv/bin/python scripts/index_rag_qdrant.py \
  --rag-input-dir artifacts/rag_inputs/B10 \
  --evidence-dir artifacts/evidence/B10 \
  --embedding-config configs/local.yaml \
  --collection enzyme_immobilization_literature_sentence_baai_bge_base_en_v1_5_768_point_schema_v1 \
  --recreate
```

检索当前 live semantic collection：

```bash
PYTHONPATH=src .venv/bin/python scripts/search_rag_qdrant.py \
  "This study soybean oil ethanol yield 93.4 8 cycles last yield" \
  --config configs/local.yaml \
  --top-k 3 \
  --usable-only
```

`--json` 输出结构化 `RetrievalResponse`；`--context` 输出 LLM-ready context。

## Query Planning / Routing

当前 retrieval 已从单路向量搜索升级为：

```text
query planner -> intent routes -> record_type-aware recall -> deterministic rerank
```

planner 识别的主意图包括：

- `strategy`：carrier/support/MOF/ZIF-8/adsorption/covalent 等。
- `condition`：loading、pH、temperature、time、buffer、mg/min/°C 等。
- `performance`：yield、activity recovery、reuse/cycles、stability、conversion 等。
- `table`：table row、comparison、substrate、yield/reusability 等。
- `enzyme` 与 `application`：lipase/BCL/CALB/PPL、biodiesel、epoxidation、furfural 等。

record-type route 会优先召回：

- `immobilization_strategy`
- `formulation_condition`
- `performance_metric`
- `table_comparison_row`
- `enzyme_identity`

rerank 会合并 vector score、route weight、record_type match、numeric overlap、metrics/extracted structured text、table intent boost 与 quality penalty。

260525 更新：rerank 已加入 lightweight lexical+dense hybrid signal，不新增外部依赖。lexical signal 覆盖 domain/material token、数值 token、英文数字词归一化（如 `ten` -> `10`）、unit token 和短语 overlap，用于提升 exact material/numeric/condition 命中。当前已补充 rare material / `enzyme@material` construct signal，并对 MinerU OCR split（如 `Lipa se@NKMOF-101-Mn`）做归一化，避免稀有 MOF 精确命中被泛化 `ZIF-8/activity` 结果压低。

为避免 fallback 新文档中的同一张表或同一文档 evidence 刷满 top-k，rerank 后增加 result diversity：精确重复的长文本 evidence 会去重；同一 `parent_source_id`、同一 `table_id`、同一文档内多条 table row 会递增降权。该规则只影响排序多样性，不覆盖 `usable_for_ranking`、`requires_review` 和 QA gate 边界。

260526 更新：推荐入口的 retrieval query 不再默认注入 `activity/recovery/reusability/stability` 这类宽泛推荐词。只有用户问题包含明确推荐/优化/最佳/should/better 等强意图时才启用推荐扩展；普通 evidence QA 走 `answer_evidence_question`，前端标题和 stream prompt 也会按证据问答处理，避免自然语言问答被错误拉向 B10 表格型推荐结果。

## Ranking 边界

`requires_review=true` 或带质量异常的记录默认不进入推荐 ranking。

MVP 查询可使用：

```text
usable_for_ranking=true
```

这可以避免 OCR 异常数字、异常百分比、疑似表格错列直接影响“最佳固化剂”推荐。

## Post-MinerU QA Gate

RAG build 后会执行 post-MinerU layout/table QA gate：

- fallback manifest 中的 `placeholder_pages` 会映射到 MinerU `page_idx`，相关 chunk/table 标记 `unrecoverable_page_placeholder`。
- 空表、缺 header、稀疏表、ragged rows、疑似旋转宽表、flattened table 会进入 `qa_status=fail`。
- QA 标记写入 `quality_flags`、`qa_flags`、`review_reasons`、`requires_review`、`usable_for_ranking`。
- `qa_status=fail` 或 placeholder 来源不会进入 rule-based evidence 抽取；已进入 Qdrant 的异常点也不会 `usable_for_ranking=true`。

## 验证标准

正式 collection 验证标准：

- 能构建并检索 `rag_chunk`、`table_record`、`evidence_record` 三类 point。
- 真实 Qdrant live collection `enzyme_immobilization_literature_sentence_baai_bge_base_en_v1_5_768_point_schema_v1` 当前应为 green，points count 为 8263。
- hash rollback collection `enzyme_immobilization_literature` 应保留，不覆盖重建。
- point type distribution 应包含 `rag_chunk=3673`、`table_record=166`、`evidence_record=4424`。
- 查询 BCL/ZIF-8 或 BCL biodiesel 能召回 enzyme identity 和 immobilization strategy。
- 查询 `This study soybean oil ethanol yield 93.4 8 cycles` 时，第一名应为 B10 this-study 表格 evidence。
- Qdrant 未启动时，离线 local search 仍可验证 embedding 和 point payload。

切换前 24-query curated benchmark：

- hash baseline：Recall@8=0.958，MRR=0.809。
- semantic candidate：Recall@8=1.000，MRR=0.931。
- 该阶段作为切换前证据；后续已扩到 62-query v3 benchmark 并完成 live 切换。

当前 62-query curated benchmark v3：

| collection | role | total pass | positive recall@k | positive MRR | ambiguous | negative | exclusion |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `enzyme_immobilization_literature` | hash rollback baseline | 57/62 | 0.900 | 0.767 | 3/5 | 5/5 | 7/7 |
| `enzyme_immobilization_literature_sentence_baai_bge_base_en_v1_5_768_point_schema_v1` | semantic live before lexical/diversity rerank | 62/62 | 1.000 | 0.895 | 5/5 | 5/5 | 7/7 |
| `enzyme_immobilization_literature_sentence_baai_bge_base_en_v1_5_768_point_schema_v1` | semantic live after lexical/diversity rerank | 62/62 | 1.000 | 0.948 | 5/5 | 5/5 | 7/7 |
| `enzyme_immobilization_literature_sentence_baai_bge_base_en_v1_5_768_point_schema_v1` | current after failed-PDF recovery + rare material OCR rerank | 62/62 | 1.000 | 0.941 | 5/5 | 5/5 | 7/7 |

v3 benchmark 包含 positive、ambiguous、negative、bad-table exclusion 和 placeholder-page exclusion。semantic collection 已达到 live 切换门槛，并已成为默认 runtime；hash collection 继续保留为 rollback baseline。默认配置切换后应持续重跑 `benchmarks/retrieval_smoke.json` 防止回归。
