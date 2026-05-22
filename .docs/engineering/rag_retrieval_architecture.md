# RAG Retrieval Architecture

## 当前目标

MVP 阶段先建立可复跑的本地 retrieval 闭环：

```text
MinerU artifact -> RAG inputs -> evidence records -> vector points -> retrieval smoke test
```

当前不是最终科学检索模型。第一目标是把 evidence traceability、metadata filter、quality flags 和 ranking 禁用边界打穿。

## Collection 设计

默认 Qdrant collection：

```text
enzyme_immobilization
```

本地 B10 smoke collection：

```text
enzyme_immobilization_b10
```

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

当前使用 `hash-v1-384` deterministic local embedding。

使用原因：

- 不依赖外部 API。
- 不需要下载模型。
- 可稳定验证 Qdrant 写入、搜索和 metadata filter。
- 便于在无网络环境中做 smoke test。

边界：

- 该 embedding 不能作为最终专业语义检索模型。
- 后续应替换为 BGE-M3、SciBERT/SPECTER 类科学文本 embedding，或领域微调 reranker。
- 替换时只改 embedding backend，不改 RAG artifact schema 和 Qdrant payload contract。

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

索引 B10：

```bash
PYTHONPATH=src .venv/bin/python scripts/index_rag_qdrant.py \
  --rag-input-dir artifacts/rag_inputs/B10 \
  --evidence-dir artifacts/evidence/B10 \
  --collection enzyme_immobilization_b10 \
  --recreate
```

检索 B10：

```bash
PYTHONPATH=src .venv/bin/python scripts/search_rag_qdrant.py \
  "This study soybean oil ethanol yield 93.4 8 cycles last yield" \
  --collection enzyme_immobilization_b10 \
  --top-k 3 \
  --usable-only
```

`--json` 输出结构化 `RetrievalResponse`；`--context` 输出 LLM-ready context。

## Ranking 边界

`requires_review=true` 或带质量异常的记录默认不进入推荐 ranking。

MVP 查询可使用：

```text
usable_for_ranking=true
```

这可以避免 OCR 异常数字、异常百分比、疑似表格错列直接影响“最佳固化剂”推荐。

## 验证标准

B10 本地 smoke test 应满足：

- 能构建 `rag_chunk`、`table_record`、`evidence_record` 三类 point。
- 真实 Qdrant collection `enzyme_immobilization_b10` points count 为 119。
- 查询 BCL/ZIF-8 能召回 enzyme identity 和 immobilization strategy。
- 查询 `This study soybean oil ethanol yield 93.4 8 cycles` 时，第一名应为 B10 this-study 表格 evidence。
- Qdrant 未启动时，离线 local search 仍可验证 embedding 和 point payload。
