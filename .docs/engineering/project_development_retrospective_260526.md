# 生机大模型项目开发复盘 260526

## 0. 文档定位

本文记录从“生物酶固定化推荐 MVP”立项到 2026-05-26 当前状态为止，项目遇到的问题、根因判断、解决动作、优化效果、验证方式和仍需处理的风险。

这不是对外宣传稿，而是工程复盘和后续交接文档。后续 agent 或开发者继续工作时，应先读本文，再按需跳转到 `.docs/index.md` 中的专题文档和代码。

当前项目主线：

```text
PDF 文献
-> 本地 MinerU 解析
-> RAG chunks / table records
-> first-pass evidence extraction
-> QA gate / curated evidence overlay
-> Qdrant semantic collection
-> retrieval planner / rerank
-> FastAPI
-> Web 工作台 / CLI
-> SiliconFlow LLM 生成 evidence-backed answer
```

当前默认 runtime：

| 层级 | 当前选择 | 状态 |
| --- | --- | --- |
| PDF parser | MinerU local 3.1.15 | 本地/LaunchAgent 可用 |
| Vector DB | Qdrant 1.18.0 | 本地 collection green |
| Live collection | `enzyme_immobilization_literature_sentence_baai_bge_base_en_v1_5_768_point_schema_v1` | 默认 live |
| Rollback baseline | `enzyme_immobilization_literature` | hash_v1 rollback |
| Historical smoke collection | `enzyme_immobilization_b10` | 只保留历史对照 |
| Embedding | `BAAI/bge-base-en-v1.5`, 768d, CPU, local cache | 默认 live |
| Generator | SiliconFlow `deepseek-ai/DeepSeek-V4-Flash` | 默认 live |
| Review LLM planned | SiliconFlow `Qwen/Qwen3.6-35B-A3B` | 规划中 |
| Frontend | Static web on `127.0.0.1:5173` | LaunchAgent 托管 |
| Backend | FastAPI on `127.0.0.1:8001` | LaunchAgent 托管 |

当前运行态关键指标，按 260525/260526 文档和验证口径：

| 指标 | 当前值 |
| --- | ---: |
| registered/searchable documents | 95 |
| indexed pages | 1004 |
| rag chunks | 3673 |
| table records | 166 |
| evidence records | 4424 |
| review items | 1245 |
| Qdrant points | 8263 |
| curated benchmark v3 cases | 62 |
| latest contract tests | 62 passed |

## 1. 初始问题：只有想法，没有可审计的科研推荐数据模型

### 现象

项目初始目标是“根据生物酶名称推荐固定化载体/固化剂/条件”，但如果直接做成 `enzyme -> carrier` 的单表或让 LLM 自由回答，会有几个致命问题：

- “最佳固定化载体”不是全局唯一答案，依赖 enzyme、应用场景、反应介质、底物、评价指标、固定化条件和 assay 条件。
- 论文中的性能指标不可直接横向比较，例如 immobilization yield、activity recovery、relative activity、reuse residual activity、biodiesel yield 对应的实验背景不同。
- 如果不保留 evidence span、页码、单位和 citation，后续无法人工复核，也无法解释推荐来源。
- LLM 很容易把“文献中出现过的方案”说成“最优方案”。

### 根因

缺少一个面向 enzyme immobilization 的结构化事实模型和推荐边界。模型需要围绕：

```text
enzyme + immobilization strategy + formulation + evaluation context + metric + evidence
```

而不是围绕单一字段 `curing_agent` 或 `carrier`。

### 解决

建立 MVP schema 和核心原则：

- `Enzyme Identity`
- `Immobilization Strategy`
- `Formulation`
- `Evaluation Context`
- `Performance Metrics`
- `Evidence / Citation`

关键约束：

- 所有推荐必须连接 evidence records。
- 所有数值必须保留 unit。
- 缺失值用 `null`，不能由模型补全。
- 区分 immobilization conditions、assay conditions、application conditions。
- ranking 由 objective 驱动，LLM 不直接拍脑袋排序。
- 不能把“最佳固化剂”表达为脱离目标、应用场景和实验条件的全局唯一答案。

### 产物

- `.docs/research/enzyme_immobilization_mvp_schema.md`
- `src/enzyme_recommender/schemas/immobilization.py`
- `schemas/examples/*.json`
- `schemas/generated/*.schema.json`
- `scripts/export_json_schema.py`
- `scripts/validate_examples.py`

### 效果

项目从“LLM 问答 demo”转成了 evidence-first RAG 系统。后面所有 ingestion、retrieval、manual review、benchmark 都围绕这个契约扩展，避免了早期架构走向不可审计的聊天机器人。

## 2. PDF 解析问题：外部 MinerU 不稳定，本地 MinerU 才能进入正式链路

### 现象

早期尝试调用天翼云/外部 MinerU endpoint，提交 PDF 后出现：

```text
POST http://220.154.141.69:8002/tasks
-> 502 Bad Gateway
```

同时，外部 endpoint 的可用性、凭证、网络路径、数据隐私和长期部署边界都不可控。

### 根因

PDF parsing 是整个知识库的第一事实源。如果解析服务不稳定或不可控，后续 RAG、evidence、benchmark、人工复核都会失去 provenance。外部 MinerU 也不适合未来公网服务端部署，因为用户上传 PDF 不应被静默转发到不可控第三方。

### 解决

明确硬约束：

- PDF parsing 只使用本地/自托管 MinerU。
- 天翼云 MinerU 只保留为历史调研，不进入 MVP、生产调用或外网部署。
- MinerU client 支持 submit base URL 和 result base URL 独立配置。
- HTTP client 对 `127.0.0.1` 调用设置 `trust_env=False`，避免本机代理劫持 localhost 请求导致 `502`。

本地部署 MinerU：

```text
Python: /opt/homebrew/bin/python3.12
MinerU: 3.1.15
API: http://127.0.0.1:8000
```

### 产物

- `.docs/research/mineru_pdf_ingestion_api.md`
- `src/enzyme_recommender/ingestion/mineru.py`
- `scripts/run_mineru_smoke.py`
- `scripts/fetch_mineru_result.py`
- `scripts/analyze_mineru_artifact.py`

### 效果

用 `B10.pdf` 完成真实 smoke test：

| 项 | 结果 |
| --- | --- |
| PDF | `B10.pdf` |
| 页数 | 14 |
| MinerU task | completed |
| result type | zip |
| result size | 687 KB |
| output | `.md`, `content_list`, `middle_json`, `model_json`, images |

最终确认 `content_list.json` 是最适合 RAG/evidence extraction 的主输入，因为它保留 block type、page index、bbox、text/table body；`md` 适合人工阅读；`middle_json/model_json/images` 适合 layout/table debug。

## 3. MinerU artifact 到 RAG 原料层：不能直接把 Markdown 喂进向量库

### 现象

MinerU 输出 Markdown 可读性不错，但如果直接拿 Markdown 做 RAG，会遇到：

- page/bbox 溯源弱。
- 表格结构容易被线性化后丢列。
- 无法区分正文 chunk、表格 chunk、抽取候选。
- 低价值短文本、参考文献、OCR 噪声容易污染索引。

### 根因

RAG 需要的是可追踪、可过滤、可复跑的数据层，不是单纯可读文本。特别是科研推荐场景，citation、page、source block、quality flag 比“读起来顺”更重要。

### 解决

建立 RAG 原料层：

```text
MinerU content_list
-> document_manifest.json
-> rag_chunks.jsonl
-> table_records.jsonl
-> extraction_candidates.jsonl
```

设计规则：

- `rag_chunks.jsonl` 作为向量库主输入，保留 `source_pdf`、`document_id`、page、bbox、section、source block indices。
- 表格单独输出 `table_records.jsonl`，保留 columns、rows、caption、html、image path。
- 表格也镜像成 table chunk 进入 RAG，以便 query 能召回表格上下文。
- `extraction_candidates.jsonl` 只是 evidence extraction 候选，不等于最终 facts。
- 短 chunk、低价值块、明显 reference cell 通过 quality flags 标记或过滤。

### 产物

- `src/enzyme_recommender/rag/artifacts.py`
- `src/enzyme_recommender/rag/chunking.py`
- `scripts/build_rag_inputs.py`

### 效果

B10 smoke 结果：

| 指标 | 数值 |
| --- | ---: |
| content items | 131 |
| pages | 14 |
| text blocks | 69 |
| rag chunks | 36 |
| text chunks | 34 |
| table chunks | 2 |
| table records | 2 |
| extraction candidates | 34 |

同时发现并标记重要 OCR/表格异常：

- Abstract 中 `1279%` 被标为 `suspicious_percent_gt_300`。
- Table 1 中 `Yield (%) = 900.00` 被标为 `suspicious_table_yield_gt_100`。
- 部分 activity recovery 段落有 OCR duplicate text。

这些发现直接推动后续 QA gate、manual review 和 ranking 禁用规则。

## 4. First-pass evidence extraction：规则抽取可打底，但必须带 review queue

### 现象

需要从 chunk/table 中抽取 enzyme、carrier、method、condition、performance metric 和 table comparison row。但直接让 LLM 抽取会带来成本、不可复跑和 JSON 不稳定问题；直接规则抽取又会受 OCR/表格错列影响。

### 根因

早期系统最需要的是稳定可复跑的 first-pass evidence，而不是最终人工级事实库。first-pass 应该尽量召回潜在事实，同时把不可靠记录送入 review queue，而不是静默当成可 ranking 事实。

### 解决

实现 rule-based evidence extractor：

record types：

- `enzyme_identity`
- `immobilization_strategy`
- `formulation_condition`
- `performance_metric`
- `table_comparison_row`

输出：

```text
evidence_records.jsonl
review_queue.jsonl
validation_report.json
```

关键策略：

- 上游 chunk/table 的 `quality_flags` 传递到 evidence。
- 表格异常只影响对应 row，不污染整张表。
- 可疑数值、OCR 重复、reference cell、yield > 100 等进入 review queue。
- first-pass evidence 不是最终 curated facts。

### 产物

- `src/enzyme_recommender/evidence/extractor.py`
- `scripts/extract_evidence_records.py`

### 效果

B10 first-pass evidence：

| 指标 | 数值 |
| --- | ---: |
| evidence records | 81 |
| review queue | 24 |
| enzyme_identity | 25 |
| immobilization_strategy | 24 |
| formulation_condition | 12 |
| performance_metric | 6 |
| table_comparison_row | 14 |

已抽到的关键事实：

- enzyme: `Burkholderia cepacia lipase / BCL`
- carrier: hierarchical mesoporous `ZIF-8`
- method: adsorption
- optimal conditions: BCL loading 700 mg, adsorption time 30 min, 25 degC, pH 7.5
- application: biodiesel / transesterification
- table row: soybean oil, solvent-free, ethanol, yield 93.4%, 8 cycles, last yield 71.3%

## 5. 初版向量检索：hash embedding 打通 smoke，但不能代表科学语义检索

### 现象

早期需要快速打通 Qdrant indexing/search，但本地模型缓存、Hugging Face 访问、MPS 运行都有不确定性。如果一开始就依赖外部模型下载，pipeline 会被环境问题阻塞。

### 根因

项目需要先验证 payload contract、point type、citation、filter、usable-only、retrieval response，而不是马上追求语义效果。

### 解决

先实现 deterministic `hash_v1` embedding：

- 无网络依赖。
- 维度可控。
- 可复跑。
- 适合 smoke 和 rollback。

同一个 Qdrant collection 中存三类 point：

- `rag_chunk`
- `table_record`
- `evidence_record`

payload 保留：

- `document_id`
- `source_pdf`
- `source_id`
- `point_type`
- page/citation/section
- `quality_flags`
- `requires_review`
- `usable_for_ranking`
- `text`
- evidence 的 `record_type`、`extracted`、`metrics`

### 产物

- `src/enzyme_recommender/rag/embedding.py`
- `src/enzyme_recommender/rag/qdrant.py`
- `src/enzyme_recommender/rag/retrieval.py`
- `scripts/index_rag_qdrant.py`
- `scripts/search_rag_qdrant.py`
- `scripts/search_rag_local.py`
- `scripts/start_qdrant_local.sh`
- `scripts/stop_qdrant_local.sh`

### 效果

打通：

```text
RAG inputs + evidence records
-> vector points
-> Qdrant collection
-> RetrievalResponse
-> LLM-ready context
```

同时明确 `requires_review=true` 和质量异常默认不进入 ranking，为后续 QA gate 和 curated evidence 奠定边界。

## 6. Recommendation / formulation service：把 RAG 结果变成可审计答案

### 现象

检索能返回 evidence，但用户需要的是：

- 推荐固定化载体/方法。
- 配方优化建议。
- 每条建议的 evidence/citation。
- 不确定性和边界条件。

如果直接把 top-k chunks 发给 LLM，输出很难稳定绑定 evidence。

### 根因

需要 service 层定义 request/response contract、prompt contract 和 fallback behavior，避免前端/CLI/API 各自拼 prompt。

### 解决

实现两个服务：

1. `RecommendationService`
   - 输入 enzyme、objective、application_context、constraints。
   - 检索 evidence。
   - 构造 evidence-first prompt。
   - 输出 candidates、limitations、next_experiment_suggestions。

2. `FormulationOptimizationService`
   - 输入 enzyme 和用户 formulation JSON。
   - 输出字段级 `changes[]`。
   - 每条 change 绑定 evidence ids 和 citations。

保留 deterministic evidence fallback：

- 当 LLM 输出不是合法 JSON 或缺少 candidates 时，仍可从 retrieval evidence 生成最低限度可审计候选。

### 产物

- `src/enzyme_recommender/recommendation/enzyme.py`
- `src/enzyme_recommender/recommendation/formulation.py`
- `scripts/recommend_by_enzyme.py`
- `scripts/optimize_formulation.py`

### 效果

系统开始从“检索工具”进入“推荐/优化助手”，但仍保留 evidence-first 边界：LLM 不能脱离 evidence context 自由发挥。

## 7. FastAPI 和 Web：从 CLI 进入可交互工作台

### 现象

CLI 可验证 pipeline，但用户需要通过浏览器输入自然语言或配方 JSON，并看到候选、证据、citation、PDF 链接。

### 根因

需要把 service 层封装成稳定 API，同时前端展示证据链，不能只显示 LLM 文本。

### 解决

新增 FastAPI：

```text
GET  /api/health
POST /api/recommend/by-enzyme
POST /api/recommend/by-enzyme/stream
POST /api/optimize/formulation
POST /api/optimize/formulation/stream
POST /api/search/evidence
GET  /api/dashboard/summary
GET  /api/pdfs/{pdf_name}
```

前端支持：

- 酶名推荐。
- 配方优化。
- 证据检索。
- live NDJSON stream。
- reference cards。
- inline citation。
- PDF page link。
- reference modal。

### 产物

- `src/enzyme_recommender/api/app.py`
- `src/enzyme_recommender/api/models.py`
- `scripts/start_api.sh`
- `web/index.html`
- `web/app.js`
- `web/styles.css`

### 效果

用户可以在工作台完成：

```text
自然语言 query
-> API retrieval
-> LLM stream
-> evidence cards
-> 点击 citation 查看 chunk/PDF
```

后续又追加了 reference table rendering，能把线性化表格恢复成可读 HTML table，并显示 table caption。

## 8. LLM 接入：从 mock 到 SiliconFlow，并处理流式体验

### 现象

mock generator 只能做 smoke。真实回答需要接入外部 LLM。但外部 LLM 有：

- API key 管理问题。
- 首 token 延迟。
- stream 中断。
- JSON response format 和 text stream 的差异。
- provider 切换需求。

### 根因

不能把 provider 逻辑散落在 recommendation/formulation 里，必须有统一 generator protocol 和 runtime config。

### 解决

建立 OpenAI-compatible generator provider：

- SiliconFlow 默认 provider。
- DeepSeek provider 预留。
- mock provider 保留测试和离线 smoke。
- API key 通过 `.env.local` / `.env` 读取，不写入仓库。
- stream 接口使用 NDJSON event：
  - status
  - retrieval
  - preview
  - delta
  - final
  - error

模型演进：

- 早期 DeepSeek/SiliconFlow 调研。
- 后续默认 live 模型设为 `deepseek-ai/DeepSeek-V4-Flash`。
- 高质量复核规划用 `Qwen/Qwen3.6-35B-A3B`，不阻塞首答。

### 产物

- `src/enzyme_recommender/generators/protocol.py`
- `src/enzyme_recommender/generators/openai_compatible.py`
- `src/enzyme_recommender/runtime/config.py`
- `src/enzyme_recommender/runtime/factory.py`
- `scripts/benchmark_siliconflow_ttft.py`
- `reports/siliconflow_ttft_*.md/json`

### 效果

前端能边检索边显示状态，并在 LLM 生成时持续输出 delta。真实用户不再面对“卡死式等待”。同时保留 mock/hash fallback，避免外部 API 不可用时项目完全不可测。

## 9. 本地持久化部署：LaunchAgents 与 macOS TCC 问题

### 现象

需要四个服务长期运行：

- Qdrant
- MinerU API
- FastAPI backend
- Static frontend

首次用 macOS LaunchAgents 直接从项目目录执行脚本时，所有服务失败：

```text
last exit code = 126
shell-init: error retrieving current directory: getcwd: cannot access parent directories: Operation not permitted
/bin/bash: .../deploy/local/bin/run_api.sh: Operation not permitted
```

### 根因

项目位于 Desktop/Documents 类路径，LaunchAgent 直接以 `WorkingDirectory` 指向这些目录并执行脚本时触发 macOS TCC/权限边界。不是脚本执行位问题，而是 launchd 对受保护目录访问不稳定。

### 解决

设计 runtime mirror：

```text
~/Library/Application Support/Shengji/
  app/      # 同步后的运行目录
  bin/      # 安装期生成 wrappers
~/Library/Logs/Shengji/
~/Library/LaunchAgents/com.shengji.*.plist
```

规则：

- LaunchAgent 不直接执行 repo 脚本。
- installer 同步 `src/web/configs/scripts/schemas` 等到 runtime mirror。
- wrappers 位于 Application Support。
- 日志集中到 `~/Library/Logs/Shengji/`。
- `.env.local` 以 mode 600 复制到 runtime mirror，不写入 plist，不打印。
- Qdrant storage/artifacts 可以按需要同步，但不进 git。

### 产物

- `deploy/local/install_launchagents.sh`
- `deploy/local/restart_launchagents.sh`
- `deploy/local/status_launchagents.sh`
- `deploy/local/sync_runtime.sh`
- `deploy/local/bin/run_*.sh`
- `deploy/local/launchd/*.plist.template`
- `.docs/engineering/local_launchagents_deployment.md`
- `.docs/engineering/system_deployment_report_260524.md`

### 效果

四个服务由 launchd 托管：

| 服务 | 地址 |
| --- | --- |
| Qdrant | `127.0.0.1:6333/6334` |
| MinerU API | `127.0.0.1:8000` |
| FastAPI | `127.0.0.1:8001` |
| Web | `127.0.0.1:5173` |

`com.shengji.logrotate` 每日轮转日志。后续发现并记住一个重要操作边界：修改 repo 代码后，LaunchAgent runtime 不会自动更新，必须执行 `deploy/local/sync_runtime.sh` 并重启相关服务。

## 10. Dashboard 统计问题：前端硬编码导致系统状态误导

### 现象

首页 `PDF 切片引擎` 卡片显示 `27 docs / 323 pages`，但这是前端硬编码，不等于 MinerU artifacts、Qdrant 或 registry 状态。

### 根因

前端没有从后端聚合真实 runtime state。知识库已经从 B10 smoke 发展到正式 collection 后，硬编码数字会误导判断，尤其是在检查是否成功索引 95 篇 PDF 时。

### 解决

新增 `/api/dashboard/summary`：

- source PDF inventory。
- processed/indexed docs。
- pages。
- rag chunks。
- table records。
- evidence records。
- curated evidence records。
- review items。
- Qdrant status/points/collection。

聚合优先级：

1. Qdrant payload 聚合。
2. 本地 artifacts manifest fallback。
3. 不可用时返回可解释状态，而不是前端崩溃。

前端启动时调用 summary API，替换硬编码。

### 产物

- `src/enzyme_recommender/api/app.py` dashboard summary functions。
- `src/enzyme_recommender/api/models.py` `DashboardSummaryResponse`。
- `web/app.js` dashboard render。
- `.docs/workflow/260524-dashboard-summary-stats.md`

### 效果

Dashboard 能反映正式 collection，而不是历史 B10 或手写数字。后续运行态可显示 95 indexed docs、1004 pages、8263 points 这一类真实指标。

## 11. PDF ingestion governance：上传成功不等于 searchable

### 现象

随着 PDF 数量增加，单篇脚本不能满足：

- sha256 去重。
- 失败重试。
- 每篇 PDF 的 stage/status。
- MinerU artifact provenance。
- Qdrant index version。
- 上传批次管理。
- 后续新增 PDF 自动入库。

### 根因

缺少 ingestion registry 和状态机。如果只看文件夹和日志，很快会出现“Qdrant 有但 artifacts 不全”“重复入库”“失败原因丢失”的不可治理状态。

### 解决

建立 ingestion registry：

```text
artifacts/
  uploads/raw/<sha256>.pdf
  ingestion_registry/documents.jsonl
  ingestion_registry/jobs.jsonl
  mineru/<document_id>/<task_id>/
  rag_inputs/<document_id>/
  evidence/<document_id>/
  indexing/<collection>/<document_id>.json
```

状态机：

```text
uploaded
-> deduplicated
-> mineru_submitted
-> mineru_succeeded
-> rag_built
-> evidence_extracted
-> indexed
-> retrieval_verified
-> searchable
```

失败状态：

```text
failed_upload_validation
failed_mineru
failed_rag_build
failed_evidence
failed_indexing
failed_retrieval_verification
needs_review
```

关键规则：

- 同一 sha256 重复上传不重复解析。
- 每阶段只读取上一阶段稳定产物。
- `searchable` 只能由 retrieval sanity check 置位，不能由 Qdrant upsert 成功直接置位。
- transient service outage 不把整批 jobs 标成 failed。
- Qdrant 不是事实源，registry/artifacts 才是事实源。

### 产物

- `src/enzyme_recommender/ingestion/registry.py`
- `src/enzyme_recommender/ingestion/pipeline.py`
- `scripts/register_pdf_corpus.py`
- `scripts/run_ingestion_worker.py`
- `src/enzyme_recommender/api/app.py` ingestion APIs
- `.docs/engineering/pdf_ingestion_data_governance.md`

### 效果

支持历史批处理和增量上传；失败可恢复；重复文档不会污染索引；dashboard 和 worker 可以围绕 registry 统一判断状态。

## 12. 19 篇 PDF 失败：repair、raster/OCR fallback 和 MinerU runtime 修复

### 现象

批处理时有 19 篇 PDF 失败：

```text
A34 A35 A39 A47 A49 A51 A53 A57 A65 A66 A68 A70 A72 A73 A74 A75 A76 A77 A78
```

失败类型分两类：

- 17 篇 `pdf_page_load_failure`
- A47/A75 为 MinerU runtime/model `state_dict` mismatch

### 根因

1. 一部分 PDF 页无法被 MinerU/PDF backend 正常加载，普通 pypdf rewrite 虽可渲染但页数减少，不满足页数保真。
2. A47/A75 原 PDF 可渲染，真正问题是 MPS 下 seal OCR server 权重 shape 和 server arch 不匹配。
3. 如果直接用缺页 PDF 入库，会造成 page/citation 错位和 evidence 丢失。

### 解决

分策略处理：

1. 对 17 篇 page load failure：
   - 使用 `pdfinfo` 获取原始页数。
   - 用 `pdftoppm` 按原始页码逐页 rasterize。
   - 异常页生成显式 placeholder。
   - 重组为同页数 image PDF。
   - 用 `ocrmypdf` 生成 searchable PDF。
   - manifest 记录 `placeholder_pages`。

2. 对 A47/A75：
   - 不走 raster fallback。
   - 补齐 `seal_lite` 权重。
   - 将 MinerU runtime 设为 CPU 模式，绕过 MPS shape mismatch。
   - 重跑原 PDF。

3. 对 A34：
   - 发现旧 job stale running，但 result endpoint 已有 zip。
   - 下载并恢复 artifact，旧 job 标记 `stale_worker_recovered`。

### 产物

- `scripts/repair_failed_mineru_pdfs.py`
- `scripts/build_pdf_raster_fallbacks.py`
- `scripts/queue_pdf_fallback_ingestion.py`
- `scripts/diagnose_mineru_model_cache.py`
- `artifacts/pdf_repair/repair_report.json`
- `artifacts/pdf_raster_fallback/fallback_report.json`

### 效果

17 篇 fallback：

| 指标 | 结果 |
| --- | ---: |
| 文档数 | 17 |
| 原始总页数 | 180 |
| 最终 fallback PDF | 17 |
| 页数保真 | 全部通过 |
| render check | 全部 `bad_pages=[]` |
| placeholder pages | 34 |
| 状态 | `fallback_ready_with_placeholders` |

最终恢复结果：

- A34 recovered。
- A47/A75 原 PDF 重跑成功。
- 17 篇 raster/OCR fallback 完成，并通过 QA gate 处理 placeholder。
- registry 达到 `searchable=95`。

### 剩余风险

placeholder 页仍表示原始 PDF 中部分页不可恢复。对应页内容不得进入 usable ranking，需要人工或更强 OCR/repair 补救。

## 13. Post-MinerU QA gate：自动质量门，防止坏表和 placeholder 污染 ranking

### 现象

抽样审计发现：

- 单栏/双栏正文 reading order 大体可用。
- 真正高风险在表格结构，尤其是旋转宽表、复杂 header、merged cells、footnote 混入数据行。
- `A14` p5 旋转宽表结构损坏，不能作为 row-level evidence。
- `B10` 续表可用，但存在 `900.00` 这类 OCR/表格错误。

### 根因

MinerU 通用配置能处理大部分单栏/双栏正文，但表格结构不是稳定事实源。没有 QA gate 时，坏表 row 会进入 evidence，进一步影响 RAG ranking 和推荐。

### 解决

新增 post-MinerU QA gate：

- 读取 fallback manifest 中的 placeholder pages。
- 映射到 MinerU 0-based `page_idx`。
- 标记 chunk/table：
  - `unrecoverable_page_placeholder`
  - `requires_review=true`
  - `usable_for_ranking=false`
- 识别空表、缺 header、稀疏表、ragged rows、疑似旋转宽表、flattened table。
- QA fail source 不进入 rule-based evidence extraction。
- 已进入 Qdrant 的异常点也不能 `usable_for_ranking=true`。

### 产物

- `src/enzyme_recommender/ingestion/qa.py`
- `scripts/build_rag_inputs.py` 集成 QA gate。
- tests 中覆盖 placeholder 和 bad table。

### 效果

placeholder/bad-table 不再直接污染 ranking。Benchmark v3 中 7 条 exclusion cases 全通过，说明 bad-table、requires_review、placeholder page 当前没有进入 usable top-k。

## 14. Semantic embedding 切换：保留 hash baseline，shadow benchmark 后再切 live

### 现象

hash_v1 能打通 smoke，但语义检索质量有限。用户也明确指出 benchmark 初期样本少、容易过拟合、Recall@k 需关注 Top-3/Top-5，并担心 query 来源泄露和简单查询偏差。

### 根因

embedding 切换是高风险操作：如果直接覆盖 live collection，可能破坏现有可用系统。需要同时保留 baseline 和 semantic shadow collection，用 benchmark 决策。

### 解决

新增 collection/index version contract：

- `rag.indexing` 统一 collection name、embedding identity、index version、point schema version。
- `collection=None` 或 `auto` 按 embedding identity 派生 collection。
- 显式 collection 保持不变。
- Qdrant payload 注入：
  - `point_schema_version`
  - `embedding_provider`
  - `embedding_model`
  - `embedding_dimensions`
  - `index_version`
  - parser/rag/evidence versions。

新增三套配置：

- `configs/local.yaml`：默认 live semantic。
- `configs/local.semantic.yaml`：semantic alias。
- `configs/local.hash.yaml`：hash_v1 rollback baseline。

执行策略：

1. 保留 `enzyme_immobilization_literature` hash baseline。
2. 建 semantic shadow collection。
3. benchmark 对比。
4. semantic 稳定优于 baseline 后切 live。

### 产物

- `src/enzyme_recommender/rag/indexing.py`
- `configs/local.yaml`
- `configs/local.semantic.yaml`
- `configs/local.hash.yaml`
- `scripts/check_embedding_runtime.py`
- `scripts/reindex_existing_rag_collection.py`
- `scripts/benchmark_retrieval.py`

### 效果

benchmark 演进：

| 阶段 | collection | queries | Recall / pass | MRR |
| --- | --- | ---: | ---: | ---: |
| 3-query smoke hash | hash | 3 | Recall@8=1.0 | 0.833 |
| 3-query smoke semantic | semantic | 3 | Recall@8=1.0 | 0.778 |
| 24-query v2 hash | hash | 24 | Recall@8=0.958 | 0.809 |
| 24-query v2 semantic | semantic | 24 | Recall@8=1.000 | 0.931 |
| 62-query v3 hash | hash | 62 | 57/62, positive recall=0.900 | 0.767 |
| 62-query v3 semantic | semantic | 62 | 62/62, positive recall=1.000 | 0.895 |
| after lexical/material rerank | semantic | 62 | 62/62 | 0.941-0.948 range |
| 260526 after routing/diversity fix | semantic | 62 | 62/62 | 0.919 |

结论：

- 3-query smoke 不足以切 live。
- 24-query 后 semantic 明显优于 hash，但仍偏 curated。
- 62-query v3 加入 negative/ambiguous/exclusion 后，semantic 达到 live 门槛。
- hash baseline 继续保留为 rollback。

## 15. Query planner / record-type-aware retrieval / rerank：从单路向量召回升级为多路检索

### 现象

纯向量搜索有几个问题：

- “BCL loading 700 mg pH 7.5” 这类条件 query 不一定优先命中 `formulation_condition`。
- “yield/reuse/cycles” 这类性能 query 需要表格和 performance metric。
- “carrier/support/MOF/ZIF-8” 需要 strategy。
- 稀有材料或数值 exact match 会被泛化语义结果压过。
- 同一表多行 evidence 可能刷满 top-k。

### 根因

RAG query 存在明确 intent 和 record_type 偏好。单路 dense recall 不理解结构化 evidence 类型，也不理解数值/token exact match 的重要性。

### 解决

新增 query planner：

- 识别 `strategy`
- `condition`
- `performance`
- `table`
- `enzyme`
- `application`

按 intent 建多路 route：

- `record_type:immobilization_strategy`
- `record_type:formulation_condition`
- `record_type:performance_metric`
- `record_type:table_comparison_row`
- `record_type:enzyme_identity`
- `point_type:evidence_record`
- `point_type:rag_chunk`
- broad fallback

rerank signal：

- vector score
- route weight
- record_type priority
- point_type priority
- numeric overlap
- structured `extracted/metrics` text
- table/context intent boost
- confidence
- QA/quality penalty
- lexical score
- rare material / `enzyme@material` signal
- OCR split normalization，如 `Lipa se@NKMOF-101-Mn`

diversity：

- 精确重复长文本去重。
- 同一 parent/table 递增降权。
- 同一 document 多条结果软降权。
- 同一 document 内多条 table row 额外降权。

### 产物

- `src/enzyme_recommender/rag/retrieval.py`
- tests 中的 retrieval planning / rerank cases。

### 效果

- `lipase@NKMOF-101-Mn` 这类稀有材料 OCR split case 恢复为 rank=1。
- `700 mg / 30 min / pH 7.5` exact condition query 更稳定命中 formulation/table evidence。
- B10/A35 等强表格不再轻易占满 top-k。
- bad quality / requires_review / qa fail 不会因 lexical boost 被拉回 usable ranking。

## 16. Qdrant payload index：让过滤检索更稳

### 现象

随着 points 到 8263，metadata filter 频繁用于 point_type、record_type、document_id、usable_for_ranking 等字段。如果没有 payload index，过滤性能和一致性会变差。

### 根因

Qdrant 对 payload filter 需要显式 index 才更稳，尤其在本地服务和未来更大 corpus 中。

### 解决

新增 payload index 脚本和 client 方法：

字段：

- `point_type`
- `record_type`
- `document_id`
- `source_pdf`
- `candidate_source`
- `curation_status`
- `qa_status`
- `usable_for_ranking`
- `requires_review`

### 产物

- `QdrantRestClient.create_payload_index()`
- `ensure_payload_indexes()`
- `list_payload_schema()`
- `scripts/ensure_qdrant_payload_indexes.py`

### 效果

live semantic collection payload indexes 已补齐，脚本返回 `all_present=true`。

## 17. 人工复核体系：学生只填中文 CSV，工程侧回灌 curated overlay

### 现象

review queue 中有大量坏表和可疑 evidence。用户要求：

- 0 基础生物学本科生/研究生也能做复核。
- 不要让学生看 JSONL、record_type、metrics_json 这种工程字段。
- 给学生极简中文 CSV。
- 学生完成后，工程侧能把中文字段转换回 curated evidence。

### 根因

工程侧 evidence schema 很完整，但不适合人工标注。人工复核流程必须降低认知负担，并且不能直接修改 raw evidence。

### 解决

建立 student-friendly review package：

学生 CSV 固定中文列：

- `任务编号`
- `PDF文件`
- `页码`
- `章节或表格`
- `内容类型`
- `需校验内容`
- `机器提取结果`
- `风险提示`
- `判定结果`
- `正确的酶/蛋白`
- `正确的载体/材料`
- `正确的固定化方法/条件`
- `正确的指标名`
- `正确的数值`
- `正确的单位`
- `正确原文或表格行`
- `错误原因或备注`
- `标注人`

内容类型映射：

- `table_comparison_row` -> `表格数据`
- `enzyme_identity` -> `酶/蛋白信息`
- `immobilization_strategy` -> `载体/材料信息`
- `formulation_condition` -> `固定化/制备条件`
- `performance_metric` -> `性能结果`
- placeholder / bad table / OCR QA -> `质量问题`

导入规则：

- `正确` -> accept decision。
- `需修改` -> edit decision，中文修正字段转换到 `edited_record`。
- `错误` -> reject decision。
- `不确定` -> 不回灌，写入二次复核 CSV。
- 非法情况不污染 curated evidence。

curated overlay 原则：

```text
raw evidence_records.jsonl 不改
curation_decisions.jsonl 记录人工决策
curated_evidence_records.jsonl 生成可 ranking curated facts
Qdrant candidate_source=curated_evidence
```

### 产物

- `scripts/export_manual_review_package.py`
- `scripts/import_student_review_csv.py`
- `scripts/curate_evidence.py`
- `.docs/engineering/manual_evidence_review.md`
- `reports/manual_review_260525*`

### 效果

当前导出状态：

| 项 | 数值 |
| --- | ---: |
| evidence review items | 1142 |
| source QA items | 103 |
| total review rows | 1245 |
| bad table rows | 1059 |
| placeholder pages | 34 |
| `学生标注表_P0P1.csv` | 1100 rows |
| `学生标注表_全部.csv` | 1142 rows |
| mapping JSONL | 1142 rows, task id unique |

最大风险来源：

- `missing_enzyme_cell`: 1043 evidence records。
- `possible_ocr_duplicate_text`: 52 evidence records / 54 source QA items。
- `suspicious_percent_gt_300`: 50 evidence records / 23 source QA items。
- placeholder source QA: 17 source rows / 34 pages。

## 18. Benchmark 体系：从小样本 smoke 到 62-query curated v3

### 现象

用户指出 62 条 query 仍然不足以支撑最终统计显著性，300-1000 条黄金集更稳；早期 3/24 条 smoke 更不能说明真实用户表现。

### 根因

RAG benchmark 存在小样本方差、数据泄露、简单查询偏差、Recall@k 不对齐 LLM context window 等风险。

### 已解决

当前已建立 62-query curated v3：

| kind | count | 目标 |
| --- | ---: | --- |
| positive | 45 | 具体 enzyme/carrier/condition/performance/table row |
| ambiguous | 5 | 多篇论文均可接受 |
| negative | 5 | corpus 外 unsupported query |
| exclusion | 7 | bad-table / placeholder / requires_review 不应入 usable ranking |

指标：

- total pass
- positive recall@k
- MRR
- plan accuracy
- by-kind pass rate
- forbidden hits
- top hits debug

### 仍需继续

62 条只是工程回归集，不是最终科学评测集。后续需要：

- 扩展到 200+，再到 300-1000。
- 引入真实用户/学生自然语言问题。
- 加入错别字、模糊指代、跨段落推理、否定/排除条件。
- 报告 Recall@3 / Recall@5 / MRR@5。
- 做数据泄露审计，区分从原文抽取 query 和真实自然语言 query。
- 增加端到端 answer faithfulness / citation support 评估。

## 19. B10 参考答案刷屏问题：不是知识库坏了，是 routing 和 diversity 不够

### 现象

用户发现：无论问什么，前端参考答案经常都是 `B10.pdf`。

### 排查

API live collection 是正确的：

```text
enzyme_immobilization_literature_sentence_baai_bge_base_en_v1_5_768_point_schema_v1
```

Qdrant/API 中不是只有 B10。手动检索：

- `magnetic Fe3O4 MIL-100 lipase immobilization` 返回 B3、C1/B13/B7 等。
- `warfarin synthesis lipase supported MOF bioreactor` 返回 C6。

所以问题不是 collection 只入了 B10。

### 根因

主要原因叠加：

1. 前端 recommend mode 的 `STREAM_TOP_K = 3`，上下文太窄。
2. recommend query builder 无论用户问什么，都注入：

```text
immobilization carrier support method conditions activity recovery yield reusability stability
```

3. “这篇用了什么载体？”这类普通问答被误当成推荐 query。
4. B10 有强表格 row，`table_comparison_row` 容易在推荐型 query 中占优。
5. diversity 当时只轻微惩罚同 parent/table，不能防止同一文档/同一表多条 evidence 进入 top-k。
6. 另有 embedding lazy-load/concurrency 风险，曾出现：

```text
Cannot copy out of meta tensor; no data! Please use torch.nn.Module.to_empty()
```

### 解决

后端：

- `build_retrieval_query()` 改为优先使用用户 application_context / constraints。
- 只有明确推荐/优化/最佳/should/better 等强意图才注入 broad recommendation terms。
- 普通问答 objective 设为 `answer_evidence_question`，只追加窄词：

```text
immobilization enzyme evidence
```

- stream prompt 对 `answer_evidence_question` 不再要求“推荐固定化载体”，而是直接回答用户问题。

前端：

- `hasRecommendationIntent()` 收紧，不再把 `carrier/support/method/condition` 本身当成推荐意图。
- recommend mode payload 根据意图设置：
  - `recommend_best_immobilization_agent`
  - `answer_evidence_question`
- stream top-k 从 3 提到 6。
- search top-k 从 5 提到 8。
- 标题按 objective 显示 `证据问答结果` 或 `固定化推荐结果`。
- 更新 asset query string，避免浏览器吃旧 JS。

retrieval diversity：

- 精确重复长文本 evidence 去重。
- 同一 parent/table 更强降权。
- 同一 document 软降权。
- 同一 document 多条 table row 额外降权。

embedding runtime：

- `SentenceEmbeddingModel` 增加 lazy-load lock。
- `RuntimeServices.embedding_model()` 改为 cached singleton。
- 对 meta tensor load error 增加 Transformers CLS pooling fallback。

### 产物

- `src/enzyme_recommender/recommendation/enzyme.py`
- `src/enzyme_recommender/rag/retrieval.py`
- `src/enzyme_recommender/rag/embedding.py`
- `src/enzyme_recommender/runtime/factory.py`
- `web/app.js`
- `web/index.html`
- `web/styles.css`
- tests 中新增 routing/diversity/embedding fallback contract。

### 效果

验证：

- `pytest tests/test_core_contracts.py -q`: 62 passed。
- `node --check web/app.js`: passed。
- `compileall`: passed。
- `/api/health`: semantic collection 正常。
- `magnetic Fe3O4 MIL-100 lipase immobilization` live search 返回 B3、B13、B7、C1、A25，不再 B10 独占。
- benchmark 仍为 62/62 passed，MRR 0.919。

这次修复说明：B10 刷屏不是“知识库源错了”，而是“入口 query intent + top-k + diversity”共同导致的排序偏差。

## 20. 前端 reference 体验：citation 能点开，但表格显示不友好

### 现象

reference modal 可以展示 chunk 文本，但线性化表格不易读；caption 和 raw table 混在 pre 文本里，学生/研究人员难以快速核对。

### 根因

后端为了 embedding 和 Qdrant payload 把表格线性化成：

```text
Columns: ...
Row 1: ...
Row 2: ...
```

这适合检索，但不适合前端阅读。

### 解决

前端增加：

- `cleanReferenceText()` 保留换行。
- `isReferenceTableText()` 判断线性化表格。
- `parseLinearizedTable()` 从 `Columns` 和 `Row N` 解析列和行。
- `splitLinearizedRows()` 支持多行 row。
- 表格 caption 单独渲染。
- 长表格不截断，正文长文本仍可“更多/收起”。
- CSS 增加 `.extracted-table-caption`。

### 产物

- `web/app.js`
- `web/styles.css`
- `web/index.html` cache bust。

### 效果

前端 reference modal 对表格 evidence 更可读，人工核对 table row、caption、raw text 更顺。

## 21. 当前测试和验证闭环

当前主要验证命令：

```bash
git diff --check
node --check web/app.js
PYTHONPYCACHEPREFIX=tmp/pycache PYTHONPATH=src .venv/bin/python -m compileall -q src scripts tests
PYTHONPATH=src .venv/bin/python -m pytest tests/test_core_contracts.py -q
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/benchmark_retrieval.py --config configs/local.yaml --json
curl -sS http://127.0.0.1:8001/api/health
curl -sS http://127.0.0.1:5173/
```

当前 contract tests 覆盖：

- runtime config。
- Qdrant vector size / payload。
- index identity。
- ingestion registry。
- curation overlay。
- student review workflow。
- retrieval benchmark helpers。
- query planning / rerank。
- QA gate。
- evidence refs。
- stream prompt。
- dashboard summary。

## 22. 当前项目架构快照

```text
src/enzyme_recommender/
  api/              FastAPI app, API models, dashboard, ingestion routes
  evidence/         rule-based extraction, curation overlay
  generators/       mock / OpenAI-compatible provider
  ingestion/        MinerU client, registry, pipeline, QA gate
  rag/              chunking, embedding, indexing, Qdrant, retrieval
  recommendation/   enzyme recommendation, formulation optimization
  runtime/          config and service factory
  schemas/          immobilization schema

scripts/
  MinerU smoke/fetch/analyze
  RAG build/index/search
  evidence extraction/curation
  ingestion worker/register/retry
  benchmark/check runtime
  manual review export/import
  deployment verification

web/
  static workbench

deploy/local/
  LaunchAgents deployment

.docs/
  project memory and workflow records
```

## 23. 剩余问题和下一步优先级

### P0：benchmark 扩展

当前 62 条只能作为工程回归集。需要扩到：

- 短期 200+。
- 中期 300-1000。

必须包含：

- 学生/用户自然语言问题。
- negative。
- ambiguous。
- bad-table exclusion。
- placeholder exclusion。
- 错别字/模糊指代。
- 多跳/跨文档。
- 条件限定和否定句。

指标必须补：

- Recall@3。
- Recall@5。
- MRR@5。
- evidence support / faithfulness。

### P0：学生复核回灌

学生开始标注后，下一步是：

1. 收到已完成 CSV。
2. 先 dry-run import。
3. 检查 `student_review_import_report.json`。
4. 检查 `student_review_uncertain_or_error.csv`。
5. 生成 curation decisions。
6. rebuild curated evidence。
7. reindex curated evidence into Qdrant。
8. benchmark 对比 raw vs curated。

### P1：人工复核 UI

当前学生流程以 CSV 为主。后续可以做前端审核页，但必须复用同一 curation overlay，不另造事实源。

### P1：检索排序继续增强

可选方向：

- Cross-encoder reranker。
- section/table parent-child chunking。
- table caption + nearby context 更强融合。
- record_type-specific top-k budgeting。
- 对 answer mode 和 recommendation mode 使用不同 retrieval profile。

### P1：review LLM

高质量复核模型不要阻塞 live answer。建议作为异步 review：

```text
live answer
-> review button / async review
-> citation issues / unsupported claims / revision suggestion
```

### P2：部署形态

LaunchAgents 已满足本地开发。公网部署需要：

- Docker Compose 或 systemd。
- object storage。
- job queue。
- worker pool。
- API auth。
- upload size / timeout / virus scan。
- secret manager。

## 24. 经验总结

1. 对科研 RAG，事实源治理比 LLM prompt 更重要。
2. PDF parsing 的失败必须显式进入 registry，不能藏在日志里。
3. MinerU 通用配置能处理大部分单栏/双栏正文，但复杂表格必须 QA gate + 人工复核。
4. `requires_review=false` 和 `usable_for_ranking=true` 是 ranking 的硬边界。
5. hash embedding 很适合 smoke/rollback，但不能代表科学语义质量。
6. semantic embedding 切 live 必须靠扩大 benchmark，而不是看 3 条 query 的体感。
7. B10 刷屏这类问题，经常不是“知识库只有 B10”，而是 query routing、top-k、rerank diversity 和 prompt objective 共同出错。
8. 学生复核流程必须用人类能理解的 CSV，而不是把工程 JSONL 丢给学生。
9. `.env.local` 管理 API key 是当前本地最佳实践；仓库只保留 `api_key_env` 名称，不保留 secret。
10. LaunchAgent 运行的是 runtime mirror，修改 repo 后必须 sync runtime 并重启服务。

## 25. 关键提交时间线

| commit | 内容 | 意义 |
| --- | --- | --- |
| `227a263` | 初始化 enzyme immobilization MVP pipeline | schema、MinerU client、smoke 脚本 |
| `4946136` | Add MinerU RAG input builder | MinerU artifact -> RAG 原料层 |
| `5443eb3` | Add first-pass evidence extraction | rule-based evidence + review queue |
| `bc64d11` | Add local RAG retrieval indexing | Qdrant indexing/search |
| `b1553f4` | Add Qdrant retrieval API | RetrievalResponse / API 化 |
| `ed4be71` | Add enzyme recommendation service | evidence-backed recommendation |
| `f2ce62f` | Add formulation optimization service | 字段级配方优化 |
| `adcf3e6` | Add FastAPI backend and frontend fetch integration | Web/API 打通 |
| `ae9a9ae` | Add local LaunchAgents deployment | 本地持久化部署 |
| `be10149` | Add ingestion registry and PDF fallback pipeline | 数据治理和失败恢复 |
| `db02c59` | Add semantic RAG indexing and retrieval QA | semantic collection、QA gate、benchmark |
| `cbdfb73` | Add local ingestion worker deployment | worker LaunchAgent/runtime sync |
| `270e26d` | Add student review import workflow | 学生中文 CSV 和回灌 |
| `a65a134` | Add manual review packages | 导出复核包 |
| `e449544` | Add evaluation and demo artifacts | benchmark/demo/report artifacts |
| `652285b` | Fix RAG routing diversity and frontend references | 修 B10 刷屏、embedding 稳定、表格 reference |

## 26. 相关文档索引

- `.docs/research/enzyme_immobilization_mvp_schema.md`
- `.docs/research/mineru_pdf_ingestion_api.md`
- `.docs/engineering/model_runtime_registry.md`
- `.docs/engineering/rag_retrieval_architecture.md`
- `.docs/engineering/local_launchagents_deployment.md`
- `.docs/engineering/system_deployment_report_260524.md`
- `.docs/engineering/pdf_ingestion_data_governance.md`
- `.docs/engineering/manual_evidence_review.md`
- `.docs/workflow/260521-mineru-smoke-test.md`
- `.docs/workflow/260524-launchagents-deployment-progress.md`
- `.docs/workflow/260524-dashboard-summary-stats.md`
- `.docs/workflow/260525-rag-pipeline-optimization.md`
