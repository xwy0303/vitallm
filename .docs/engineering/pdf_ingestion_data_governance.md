# PDF Ingestion Data Governance

## 目标

系统必须支持两类 PDF ingestion：

- 历史批处理：把当前 97 篇 PDF 补齐到正式知识库。
- 增量上传：用户上传 1 篇或一批 PDF 后，系统自动完成 data governance、MinerU 解析、RAG/evidence 产物生成、Qdrant 入库，并让大模型通过 RAG 使用新知识。

核心原则：上传成功不等于进入知识库；只有完成 `PDF inventory -> MinerU artifact -> RAG inputs -> evidence records -> Qdrant points -> retrieval sanity check` 才能标记为 searchable。

## 成功标准

- 每个 PDF 有稳定 `document_id`、`sha256`、原始文件路径、上传来源、task_id、MinerU 参数、artifact 路径、RAG/evidence 路径、Qdrant collection 和 indexing version。
- 同一 PDF 重复上传必须幂等：相同 `sha256` 不重复解析，不重复生成 points，不污染 review queue。
- 任何阶段失败必须有可恢复状态和错误分类；不能只在日志里丢异常。
- Qdrant 中每个 point 可以追溯到 `document_id`、`source_pdf`、page、source block、artifact version。
- 新文档入库后，`/api/search/evidence` 和推荐/配方优化接口无需重启即可检索到新增 evidence。
- 正式 collection 不再使用 `enzyme_immobilization_b10`；历史 collection 只作为 rollback。

## 目录与数据边界

推荐 runtime 数据目录：

```text
artifacts/
  uploads/
    raw/<sha256>.pdf
    batches/<batch_id>.json
  ingestion_registry/
    documents.jsonl
    jobs.jsonl
  mineru/
    <document_id>/<task_id>/...
  rag_inputs/
    <document_id>/
  evidence/
    <document_id>/
  indexing/
    <collection>/<document_id>.json
```

说明：

- `uploads/raw` 只存原始 PDF，以 `sha256` 命名；展示名保存在 registry，不作为唯一键。
- `document_id` 默认从规范化文件名生成，但必须允许冲突后加短 hash，例如 `A14` 或 `A14_f3c9a1b2`。
- MinerU 原始 artifact 永远不覆盖；同一 PDF 用不同 MinerU/options 重跑时生成新 `artifact_version`。
- `rag_inputs` 和 `evidence` 是可复跑派生产物，允许通过 registry 校验后重建。
- Qdrant storage 是索引层，不是唯一事实来源；不能出现“Qdrant 有但 artifacts 没有”的长期状态。

## Registry Contract

必须维护 ingestion registry。MVP 可先用 JSONL，后续迁到 SQLite/Postgres。

`documents.jsonl` 每行最少字段：

```json
{
  "document_id": "A14",
  "source_pdf": "A14.pdf",
  "sha256": "...",
  "size_bytes": 1234567,
  "page_count": 27,
  "upload_batch_id": "batch_260524_001",
  "uploaded_at": "2026-05-24T00:00:00Z",
  "current_status": "searchable",
  "active_artifact_version": "mineru_3.1.15_pipeline_en_v1",
  "active_index_version": "hash_v1_768_v1"
}
```

`jobs.jsonl` 每行最少字段：

```json
{
  "job_id": "ingest_A14_...",
  "document_id": "A14",
  "sha256": "...",
  "stage": "qdrant_index",
  "status": "succeeded",
  "attempt": 1,
  "started_at": "...",
  "finished_at": "...",
  "error_code": null,
  "error_message": null
}
```

## 状态机

PDF ingestion 使用有限状态机管理，状态定义集中在 `src/enzyme_recommender/ingestion/state_machine.py`。任何 worker、恢复脚本或人工补跑入口都不能跳过 FSM 直接写散落状态字符串。

| 状态 | 阶段含义 | 必须存在的关键产物 | 下一步 |
| --- | --- | --- | --- |
| `uploaded` | PDF 已进入 registry，尚未完成去重/规范化 | `documents.jsonl` | `deduplicated` |
| `deduplicated` | 原始 PDF 已有稳定 `document_id/sha256/raw_pdf_path` | raw PDF | `mineru_submitted` |
| `mineru_submitted` | 已向 MinerU 提交任务并记录 `task_id` | MinerU job manifest | `mineru_succeeded` |
| `mineru_succeeded` | MinerU artifact 可被定位到 `auto` 目录 | `*_content_list.json` / middle json | `rag_built` |
| `rag_built` | 已生成 RAG 输入层 | `document_manifest.json`、`rag_chunks.jsonl`、`table_records.jsonl` | `evidence_extracted` |
| `evidence_extracted` | 已生成机器 evidence 和 review queue | `evidence_records.jsonl`、`review_queue.jsonl` | `indexed` |
| `indexed` | 当前文档 points 已 upsert 到目标 collection | indexing manifest、Qdrant points | `retrieval_verified` |
| `retrieval_verified` | document_id/source_pdf/context point sanity check 通过 | Qdrant scroll 可验证 | `searchable` 或 `needs_review` |
| `searchable` | 可被 RAG 正常检索，且有可用 context/evidence | registry、artifact、Qdrant 三方一致 | 终态 |
| `needs_review` | 有可检索上下文，但无可用 evidence 或质量风险需要人工复核 | context points、review flags | 终态，人工复核后可重建 curated overlay |
| `failed_upload_validation` | PDF 文件校验失败 | 错误码和错误消息 | 修复输入后从 upload validation 重试 |
| `failed_mineru` | MinerU 解析失败或服务异常 | MinerU 错误、可选 partial artifact | 原 PDF retry 或 fallback 路径 |
| `failed_rag_build` | artifact 到 RAG inputs 构建失败 | 可复用 MinerU artifact | 从 `rag_build` 恢复 |
| `failed_evidence` | evidence 抽取失败 | 可复用 `rag_inputs` | 从 `evidence_extract` 恢复 |
| `failed_indexing` | Qdrant 建点或 upsert 失败 | 可复用 `rag_inputs/evidence` | 从 `qdrant_index` 恢复 |
| `failed_retrieval_verification` | Qdrant 有写入但 sanity check 未通过 | Qdrant payload 或 mismatch 错误 | 从 `retrieval_verify` 或上游修复后恢复 |

正常 MinerU 路径：

```text
uploaded
-> deduplicated
-> mineru_submitted
-> mineru_succeeded
-> rag_built
-> evidence_extracted
-> indexed
-> retrieval_verified
-> searchable | needs_review
```

OCR/raster fallback 路径：

```text
failed_mineru
-> pdf_raster_fallback/<document_id>/fallback_manifest.json
-> fallback_ready | fallback_ready_with_placeholders
-> queue_fallback_ingestion
-> deduplicated
-> mineru_submitted
-> mineru_succeeded
-> rag_built
-> evidence_extracted
-> indexed
-> retrieval_verified
-> searchable | needs_review
```

`fallback_manifest.json` 不是入库完成标志，只表示 fallback PDF 已准备好进入同一条 ingestion pipeline。带 `placeholder_pages` 的 fallback 文档必须在 RAG build 阶段进入 QA gate，并给对应 chunk/table 打：

- `quality_flags` 包含 `unrecoverable_page_placeholder`
- `requires_review=true`
- `usable_for_ranking=false`

`fallback_ready`、`needs_review`、`searchable` 的区别：

- `fallback_ready`：仅表示 OCR/raster PDF 已生成且页数保真，可以排队进入 MinerU；此时还不能被 RAG 检索。
- `needs_review`：已完成 Qdrant 入库并能检索到上下文，但 evidence 为空或存在质量风险；可以作为人工复核线索，不能直接作为高置信 ranking 事实。
- `searchable`：registry、artifact、Qdrant 三方一致，document filter 能查到 context points，source_pdf 匹配，并通过 retrieval sanity check。

状态推进规则：

- 每一步只读取上一阶段的稳定产物，不从临时目录继续。
- 每一步完成后写 registry，再进入下一步。
- 失败后保留上游产物和错误上下文，允许从失败阶段重试。
- `searchable` 只能由 retrieval sanity check 置位，不能由 Qdrant upsert 成功直接置位。
- `pipeline.py` 必须通过 `assert_transition()` 推进状态；恢复脚本只能使用显式 `allow_recovery=True` 的阶段级恢复转移。
- Qdrant 不可用时，审计脚本必须输出 `qdrant_points=unknown`，不能把 unknown 误判为 `0`。

## 缺口审计与阶段级恢复

新增两个工程入口：

```text
PYTHONPATH=src python scripts/audit_pdf_ingestion_status.py --skip-qdrant --json
PYTHONPATH=src python scripts/recover_pdf_ingestion_gaps.py --document-id A34
```

`scripts/audit_pdf_ingestion_status.py` 是只读诊断脚本，默认检查当前 21 篇缺口文档：

```text
A27,A34,A35,A39,A41,A47,A49,A51,A53,A57,A65,A66,A68,A70,A72,A73,A74,A75,A76,A77,A78
```

审计字段固定为：

```text
document_id
source_pdf
registry_status
fallback_manifest_exists
fallback_status
placeholder_pages
queued_job
latest_job_stage
latest_job_status
mineru_artifact_exists
rag_inputs_exists
evidence_exists
qdrant_points
searchable
next_action
blocking_reason
```

`next_action` 的恢复语义：

| `next_action` | 执行含义 |
| --- | --- |
| `register_source_pdf` | registry 中缺文档，先注册原始 PDF |
| `run_queued_job` | 已有 queued ingestion job，优先消费现有队列，避免重复排队 |
| `wait_for_running_job` | 已有 running job，等待当前任务结束后再审计 |
| `queue_fallback_ingestion` | fallback PDF 已 ready，只排队进入同一 ingestion pipeline |
| `run_mineru_original_pdf` | A47/A75 这类 MinerU runtime/model 问题，重试原 PDF，不走 raster fallback |
| `build_rag_from_artifact` | 已有 MinerU artifact，从 RAG build 恢复 |
| `extract_evidence` | 已有 `rag_inputs`，从 evidence 抽取恢复 |
| `index_only` | 已有 evidence，只做 Qdrant indexing 和 retrieval verify |
| `verify_only` | Qdrant 有 points 但 registry 未进入终态，只做 retrieval sanity check |
| `blocked` | 缺少可复用上游产物，或 fallback manifest 未 ready |

`scripts/recover_pdf_ingestion_gaps.py` 默认 dry-run，只报告计划动作；必须显式加 `--execute` 才会创建 fallback job、消费已有 queued job 或运行阶段级恢复 pipeline。恢复时每篇独立失败，不阻塞整批。

## 自动化流程

用户上传单篇或批量 PDF：

1. API 接收上传，写入临时 upload staging。
2. 校验文件类型、大小、PDF 页数、sha256。
3. 将原始 PDF 移动到 `artifacts/uploads/raw/<sha256>.pdf`。
4. 写入 `documents.jsonl` 和 upload batch manifest。
5. 创建 ingestion job。
6. Worker 调 MinerU `/tasks`，保存 `task_id`、options、提交响应。
7. Worker 轮询 MinerU result，下载并解压 artifact。
8. 运行 `build_rag_inputs()` 生成 RAG inputs。
9. 运行 `extract_evidence_records()` 生成 evidence 和 review queue。
10. 运行 `build_index_points()`，用当前 embedding/index version 生成 Qdrant points。
11. Upsert 到正式 collection。
12. 执行 retrieval sanity check：
    - document_id filter 能 scroll 到 points。
    - 至少存在 `rag_chunk` 或 `table_record`。
    - 若有可用 evidence，`usable_for_ranking=true` 的记录数量被统计。
    - citation 能映射回原始 PDF。
13. 标记 `searchable`，dashboard summary 自动更新。

批量上传时每个 PDF 独立推进状态，batch 只负责聚合进度；不能因为一篇失败阻塞整批。

## Collection 与版本策略

正式 collection 推荐：

```text
enzyme_immobilization_literature
```

版本字段必须进入 registry 和 Qdrant payload：

- `parser_provider`: `mineru_local`
- `parser_version`: 例如 `3.1.15`
- `parser_options_hash`
- `rag_builder_version`
- `evidence_extractor_version`
- `embedding_provider`
- `embedding_model`
- `embedding_dimensions`
- `index_version`

Qdrant point id 必须稳定：

```text
uuid5(payload_key + index_version)
```

这样同一文档同一版本重跑是幂等 upsert；换 embedding 或 parser 版本时可写入新 collection 或新 index version。

## 与大模型 RAG 的接入

大模型不能直接读 PDF 或 MinerU artifact。推荐链路固定为：

```text
user query
-> EvidenceRetriever
-> Qdrant metadata filter / vector search
-> RetrievalResponse
-> recommendation/formulation prompt builder
-> generator provider
-> structured answer with citations
```

新增 PDF 进入 `searchable` 后，retriever 使用同一个 collection 即可召回新 evidence。LLM 层不需要知道 PDF 上传流程，只消费 retrieval hits。

重要边界：

- `requires_review=true` 默认不进入 ranking。
- review queue 可展示给人工审核，但不能自动提升为 curated evidence。
- 无 evidence 的文档仍可通过 `rag_chunk` 参与上下文召回，但推荐排序必须标注低置信度或不进入 candidate ranking。

## API 规划

已落地接口：

```text
POST /api/ingestion/uploads
POST /api/ingestion/uploads/raw
GET  /api/ingestion/batches/{batch_id}
GET  /api/ingestion/documents/{document_id}
POST /api/ingestion/documents/{document_id}/retry
POST /api/ingestion/documents/{document_id}/reindex
GET  /api/ingestion/summary
```

实现位置：

- `src/enzyme_recommender/ingestion/registry.py`：JSONL registry、PDF 校验、sha256 去重、batch/job 记录。
- `src/enzyme_recommender/ingestion/pipeline.py`：MinerU -> RAG inputs -> evidence -> Qdrant -> retrieval verification 状态机。
- `scripts/run_ingestion_worker.py`：本地 worker，处理 queued ingestion jobs。
- `src/enzyme_recommender/api/app.py`：上传、批次查询、文档查询、重试、reindex、summary API。

上传响应只返回 batch/job 状态，不承诺立即 searchable。`POST /api/ingestion/uploads` 支持 JSON payload：

```json
{
  "files": [
    {
      "filename": "A79.pdf",
      "content_base64": "<base64 pdf bytes>"
    }
  ],
  "paths": [],
  "uploaded_by": "api",
  "run_pipeline": false
}
```

`POST /api/ingestion/uploads/raw` 支持 `Content-Type: application/pdf`，文件名从 `X-Filename` header 读取。

返回示例：

```json
{
  "batch_id": "batch_260524_001",
  "documents": [
    {
      "document_id": "A79",
      "sha256": "...",
      "status": "uploaded"
    }
  ]
}
```

说明：

- `run_pipeline=false` 是默认生产路径，只注册 PDF 并创建 queued job。
- `run_pipeline=true` 只用于 smoke 或小批量同步处理；MinerU 解析耗时长，不建议前端长期持有 HTTP。
- 重复上传同一 sha256 不会重新排队，除非显式 retry/reindex。
- `/api/pdfs/{pdf_name}` 已兼容 registry 中的 uploaded PDFs，citation 可回源到 `artifacts/uploads/raw/<sha256>.pdf`。

## Worker 规划

MVP 已提供本地后台 worker：

```text
PYTHONPATH=src .venv/bin/python scripts/run_ingestion_worker.py --once
PYTHONPATH=src .venv/bin/python scripts/run_ingestion_worker.py
PYTHONPATH=src .venv/bin/python scripts/run_ingestion_worker.py --document-id A79 --once
```

常用参数：

- `--config configs/local.yaml`
- `--artifact-root artifacts`
- `--mineru-timeout-seconds 1800`
- `--mineru-interval-seconds 10`
- `--qdrant-batch-size 64`
- `--reuse-mineru-artifacts`
- `--reindex-only`
- `--delete-existing-points`

当前 worker 的关键保护：

- 若文档已经在目标 collection 中处于 `searchable` 或 `needs_review`，重复 queued job 会被跳过，避免重复 PDF 或重复排队污染索引。
- `--reuse-mineru-artifacts` 只复用能定位到 `*_content_list.json` 的 MinerU `auto` 目录；无效 task 根目录会重新提交 MinerU。
- 遇到本机 MinerU/Qdrant `Connection refused` 这类 transient service outage 时，worker 立即退出并保留剩余 queued jobs，避免把整批队列雪崩式标成 `failed_mineru`。

后续服务化：

- 单机：FastAPI + SQLite + background worker。
- 多机：API server + job queue + worker pool + shared object storage + Qdrant。

Worker 必须限制并发：

- MinerU parse 并发：默认 1-2。
- RAG/evidence CPU 并发：按机器核数配置。
- Qdrant upsert batch size：默认 64 或 128。

当前 worker 为单进程串行执行，满足本地 MinerU 并发约束。后续如接入 LaunchAgent，必须把 worker 日志纳入 `deploy/local` 日志轮转。

## 已实现版本字段

当前 Qdrant payload 已注入：

```text
ingestion_sha256
ingestion_batch_id
parser_provider
parser_version
rag_builder_version
evidence_extractor_version
embedding_provider
embedding_model
embedding_dimensions
index_version
```

当前 point id 规则为：

```text
uuid5(payload_key:index_version)
```

这样同一文档同一 index version 重跑是稳定 upsert；`/reindex` 可先按 `document_id` 删除旧 points，再写入新版本。

## Dashboard 指标

dashboard summary 至少拆分：

- `source_pdf_count`
- `source_pdf_pages`
- `mineru_succeeded_docs`
- `rag_built_docs`
- `evidence_extracted_docs`
- `indexed_docs`
- `searchable_docs`
- `failed_docs`
- `review_items`
- `curated_evidence_records`
- `qdrant_points`

不能再用单个 `docs` 同时代表 PDF inventory、RAG artifacts 和 Qdrant indexed docs。

## 当前 97 篇治理结果

截至 2026-05-25，全量正式 collection 已按 registry/artifacts 重建，而不是文件夹级重命名；历史失败 PDF 已恢复到可检索状态。

当前事实：

- source PDF: 97
- unique registered documents: 95（2 个 sha256 重复）
- live semantic collection: `enzyme_immobilization_literature_sentence_baai_bge_base_en_v1_5_768_point_schema_v1`
- hash rollback baseline: `enzyme_immobilization_literature`
- searchable documents: 95
- failed MinerU documents: 0
- Qdrant points: 8263
- point type distribution: `rag_chunk=3673`, `table_record=166`, `evidence_record=4424`
- review queue records: 1245
- curated evidence records: 0
- historical B10 rollback collection: `enzyme_immobilization_b10` 保留

历史失败清单：

```text
A34 A35 A39 A47 A49 A51 A53 A57 A65 A66 A68 A70 A72 A73 A74 A75 A76 A77 A78
```

历史失败分类与恢复状态：

- `Failed to load page.`：17 篇已通过 page-count preserving raster/OCR fallback 入库；placeholder pages 由 post-MinerU QA gate 标记为不可 ranking。
- `Error(s) in loading state_dict for BaseModel`：A47、A75 由 MinerU seal OCR 模型 cache/device 分支触发；已设置 `MINERU_DEVICE_MODE=cpu` 并补齐 `seal_lite` 权重，重跑原 PDF 成功。
- A34 stale `running` job 已通过复用 MinerU result zip 恢复并重新入库。

已完成治理动作：

1. 为 97 篇生成 `documents.jsonl`，补 sha256、page_count、source_pdf。
2. 已全量重建 semantic live collection，并保留 hash rollback baseline。
3. 已有 MinerU artifact 仅在可定位 `*_content_list.json` 时复用；无有效 artifact 的 PDF 重新提交 MinerU。
4. A56 曾因本机服务中断失败，已单独重试并成功进入正式 collection。
5. RAG/recommendation smoke 已使用正式 collection 验证通过。
6. `enzyme_immobilization_b10` 保留为 rollback，未删除。

已完成补救动作：

1. 对 17 个 `Failed to load page.` PDF 使用 page-count preserving raster/OCR fallback 入队并重跑 MinerU/RAG/Qdrant。
2. 对 A47/A75 修复 MinerU local runtime/model 分支后单篇重试原 PDF。
3. 修复后的文档已写入 live semantic collection；hash collection 只做 rollback/benchmark baseline。
4. `review_queue` 已具备 `curated_evidence_records.jsonl` overlay 机制；原始 `evidence_records.jsonl` 保持 first-pass 不可篡改。

## 验证标准

每批 ingestion 完成后必须输出：

- 输入 PDF 数、去重数、失败数。
- 每个阶段的 doc count。
- MinerU 成功/失败 task_id 列表。
- RAG chunks/table records/evidence records/review items count。
- Qdrant points count 和 per-point-type count。
- document_id filter scroll sanity check。
- 至少 3 条固定 query 的 retrieval smoke 结果。

全量治理完成标准：

- `unique_registered_documents == searchable_docs`，除非有明确 `failed_*` 或 `needs_review` 列表；`source_pdf_count` 可以大于 unique documents，因为存在 sha256 重复 PDF。
- 正式 collection points 可由 artifacts 全量重建。
- 任意 citation 可回到 PDF 文件和 page。
- recommendation/formulation API 使用正式 collection，旧 collection 可一键回滚。
