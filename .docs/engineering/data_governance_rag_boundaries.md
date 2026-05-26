# Data Governance / RAG Branch Boundaries

## 目标

为并行开发建立可执行边界：

- `data-dev` 负责 ingestion、QA、evidence provenance 和可追溯性。
- `ai-backend` 负责 retrieval、ranking、query planning 和 recommendation/formulation 的 evidence 消费。

两条线可以并行，但必须共享同一套冻结 contract。任何跨越 contract 的改动，都不能在分支里各自偷改后再碰运气 merge。

## 推荐工作树布局

```text
/Users/way/Desktop/99-生机大模型           -> dev
/Users/way/Desktop/99-生机大模型-data      -> data-dev
/Users/way/Desktop/99-生机大模型-rag       -> ai-backend
```

规则：

- 不同会话使用不同 worktree。
- 不同 worktree 使用不同 branch。
- `dev` 只做集成，不做双会话并行主战场。

## 分支职责

### `data-dev`

主责范围：

- `src/enzyme_recommender/ingestion/*`
- `src/enzyme_recommender/evidence/*`
- `scripts/run_ingestion_worker.py`
- `scripts/export_manual_review_package.py`
- `scripts/import_student_review_csv.py`
- `.docs/engineering/pdf_ingestion_data_governance.md`
- `.docs/engineering/manual_evidence_review.md`

允许负责的改动：

- PDF registry、job state machine、幂等和 provenance。
- MinerU artifact 进入 `rag_inputs` / `evidence` 的数据治理流程。
- QA flags、review queue、manual curation overlay。
- `rag_chunk` / `table_record` / `evidence_record` 的值填充逻辑。

默认不要跨线去改：

- retrieval planner、route weight、rerank 策略。
- recommendation / formulation prompt 和 response 组装。
- 前端消费字段命名。

### `ai-backend`

主责范围：

- `src/enzyme_recommender/rag/retrieval.py`
- `src/enzyme_recommender/recommendation/*`
- `src/enzyme_recommender/runtime/*`
- retrieval benchmark / evaluation 脚本
- query building、route design、ranking policy

允许负责的改动：

- query planner、intent routing、dense/lexical rerank。
- retrieval query 构造和 `usable_only` 检索策略。
- recommendation / formulation 的 evidence 组织方式。
- API 在不破坏既有 response schema 前提下的 retrieval 行为增强。

默认不要跨线去改：

- raw PDF 上传、registry 状态机、artifact 目录契约。
- first-pass evidence 抽取语义。
- manual review accept/edit/reject 流程。

## 冻结 Contract

### 1. Chunk / Document / Evidence Payload Schema

这是 data governance 和 RAG 共用的第一层 contract。字段名、类型和语义要稳定。

当前冻结的通用 payload 字段：

- `document_id: str`
- `source_pdf: str`
- `source_id: str`
- `point_type: "rag_chunk" | "table_record" | "evidence_record"`
- `page_start: int | null`
- `page_end: int | null`
- `section: str | null`
- `citation: str | null`
- `text: str`
- `quality_flags: list[str]`
- `review_reasons: list[str]`
- `requires_review: bool`
- `usable_for_ranking: bool`
- `qa_status: "pass" | "warning" | "fail" | null`
- `qa_flags: list[str]`
- `candidate_source: str | null`

`evidence_record` 冻结附加字段：

- `record_type: "enzyme_identity" | "immobilization_strategy" | "formulation_condition" | "performance_metric" | "table_comparison_row" | null`
- `parent_source_id: str | null`
- `confidence: str | null`
- `source_evidence_id: str | null`
- `extracted: dict`
- `metrics: list[dict]`
- `curation_status: str | null`
- `reviewed_by: str | null`
- `reviewed_at: str | null`

冻结语义：

- `requires_review=true` 的记录默认不能作为推荐 ranking 的可用事实。
- `qa_status=fail` 的 source/evidence 不能进入 `usable_for_ranking=true`。
- `candidate_source=curated_evidence` 表示来自人工 overlay，而不是覆盖原始 `evidence_records.jsonl`。
- `citation` 格式保持 `A21.pdf:p10` 或 `A21.pdf:p10-p11`，不能随意改为别的样式。

允许的演化方式：

- 新增可选字段：允许。
- 给现有字段补更严谨的值：允许。
- 重命名、删除、改类型、改布尔语义：必须同步两条线、更新本文件并补 contract tests。

### 2. Qdrant Collection / Metadata Contract

这是 retrieval 和 indexing 共用的第二层 contract。

当前冻结项：

- collection 命名入口只有 `src/enzyme_recommender/rag/indexing.py`
- `point_schema_version` 当前固定为 `point_schema_v1`
- live semantic collection 作为默认 runtime
- hash collection 作为 rollback baseline，不能被覆盖重建

当前检索/过滤依赖的 metadata 字段：

- `point_type`
- `record_type`
- `document_id`
- `source_pdf`
- `candidate_source`
- `curation_status`
- `qa_status`
- `usable_for_ranking`
- `requires_review`

规则：

- data governance 可以新增 provenance / QA metadata，但不能删除或重命名上述既有字段。
- RAG 可以新增基于 metadata 的过滤逻辑，但只要新字段进入 query filter，就必须同步 payload index 和 tests。
- collection 名称、embedding 维度、`index_version`、`point_schema_version` 任一变化，都视为 reindex 级别改动，不能在两条线各自偷偷推进。

### 3. Retrieval Input / Output Contract

这是 `ai-backend` 对外暴露给 recommendation、API 和前端的 contract。

当前冻结的 retrieval 输入：

- `query`
- `collection`
- `point_type`
- `usable_only`
- `top_k`

当前冻结的 `RetrievalResponse` 字段：

- `query`
- `collection`
- `embedding_model`
- `top_k`
- `usable_only`
- `point_type`
- `query_plan`
- `hits`

当前冻结的 `RetrievalHit` 核心字段：

- `score`
- `vector_score`
- `rerank_score`
- `lexical_score`
- `route_weight`
- `route_labels`
- `point_type`
- `source_id`
- `document_id`
- `source_pdf`
- `citation`
- `page_start`
- `page_end`
- `section`
- `record_type`
- `confidence`
- `candidate_source`
- `qa_status`
- `quality_flags`
- `review_reasons`
- `requires_review`
- `usable_for_ranking`
- `extracted`
- `metrics`
- `text`
- `source_chunk_text`

规则：

- `ai-backend` 可以调整 planner、route、rerank、dedupe 和 diversity。
- `data-governance-dev` 不应依赖 planner 内部细节，只依赖稳定 payload 和 metadata。
- 如果 data governance 需要让 retrieval 感知新的质量状态，应新增显式 metadata 字段，不要把规则偷偷塞进 `text`。

### 4. Frontend / API Response Contract

这是后端返回给前端和调用方的第三层 contract。虽然本轮重点是 data governance 与 RAG，但这层必须冻结，否则两条线 merge 后会把前端一起带崩。

当前冻结的 API request 字段：

- `POST /api/search/evidence`: `query`, `collection`, `point_type`, `usable_only`, `top_k`
- `POST /api/recommend/by-enzyme`: `enzyme_name`, `objective`, `application_context`, `constraints`, `collection`, `top_k`
- `POST /api/optimize/formulation`: `enzyme_name`, `user_formulation`, `objective`, `application_context`, `constraints`, `collection`, `top_k`

当前冻结的前端消费字段：

- health: `generator_provider`, `collection`
- search: `hits`
- recommend / optimize: `objective`, `generator_provider`, `generator_model`, `limitations`, `evidence_hits`

前端对 hit 级字段的稳定依赖：

- `citation`
- `source_pdf`
- `page_start`
- `score`
- `record_type`
- `point_type`
- `source_chunk_text` 或 `text`

规则：

- `ai-backend` 如果只改 ranking，不应改 response shape。
- `data-dev` 不应直接改 recommendation/search response 的字段名。
- 若必须改 response schema，先在 `dev` 冻结新 contract，再让前端同步，不能把 schema 改造拆到这两条线里各做一半。

## 共享文件与主责归属

以下文件天然是冲突高发区，需要明确 lead branch：

- `src/enzyme_recommender/rag/qdrant.py`
  - payload 构造、QA/curation 字段写入：`data-dev` lead
  - search client/filter/index helper：`ai-backend` lead
- `src/enzyme_recommender/rag/indexing.py`
  - collection / index identity：共享；任何改动都要双边同步
- `src/enzyme_recommender/api/models.py`
  - ingestion models：`data-dev` lead
  - retrieval / recommend / optimize models：`ai-backend` lead
- `src/enzyme_recommender/api/app.py`
  - ingestion routes：`data-dev` lead
  - search / recommend / optimize routes：`ai-backend` lead
- `tests/test_core_contracts.py`
  - 任一分支只要改 contract，就必须一起补

规则：

- 同一共享文件如果两条线同一轮都要动，先确定 lead branch。
- follow branch 不抢先改 contract，先 rebase 再补自己的行为层改动。

## Merge 顺序

### 场景 A：只改 retrieval / ranking / recommendation

顺序：

1. `ai-backend` 合并到 `dev`
2. 跑 retrieval benchmark 和 API smoke
3. `data-dev` 后续 rebase 到新的 `dev`

### 场景 B：涉及 payload、QA、curation、index version 或 collection 变化

顺序：

1. `data-dev` 先合并到 `dev`
2. 重建受影响的 artifacts / points
3. 跑 ingestion sanity checks 和 contract tests
4. `ai-backend` rebase 到新的 `dev`
5. 重新跑 retrieval benchmark / recommendation smoke
6. 再合并 `ai-backend`

禁止动作：

- 两条线分别改 `point_schema_version` 和 retrieval filter，然后直接 merge。
- 一条线改 payload 字段名，另一条线改前端/API 响应映射，但不先在 `dev` 对齐。
- 在 `prod` 或 `test` 上直接承接未完成 contract 重构。

## 验证闭环

### `data-dev` 必跑

- `tests/test_core_contracts.py`
- ingestion summary / registry 状态检查
- 过滤前后文档数、chunk 数、evidence 数、review 数
- `requires_review=true` 和 `qa_status=fail` 不得产出 `usable_for_ranking=true`
- citation 可回源到原始 PDF

### `ai-backend` 必跑

- retrieval benchmark
- `/api/search/evidence` response shape smoke
- recommendation / formulation smoke
- rerank 后 bad-table / placeholder / review-gated evidence 不得冲进可用 top-k

### 集成到 `dev` 后必跑

- `/api/health`
- `/api/dashboard/summary`
- `/api/search/evidence`
- `POST /api/recommend/by-enzyme`
- `POST /api/optimize/formulation`
- 代表性 benchmark query

## 当前执行建议

按仓库当前状态，推荐分法如下：

- `data-dev`：继续推进 PDF ingestion、QA gate、manual review overlay、artifact provenance。
- `ai-backend`：继续推进 query planning、record-type routing、rerank、recommendation / optimization evidence usage。

只有在以下情况下，才把两条线重新并成一个会话：

- 本轮要同时修改 payload schema 和 retrieval contract。
- 两条线连续数天都在改同一批共享文件。
- benchmark 回归定位不清，需要在同一上下文里联合调试。
