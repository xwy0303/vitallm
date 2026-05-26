# Model Runtime Registry

## 硬约束

PDF parsing 只使用自托管/本地 MinerU 服务。

天翼云 MinerU 不进入后续 MVP、外网部署或生产调用路径。此前天翼云 API 只作为历史调研来源保留，不作为可切换 provider。

后续会把整个服务部署到公网，外部用户通过自有服务接口调用；外部请求不得直连用户本机或内网 MinerU。

主要生成 LLM 现在已经接入 SiliconFlow API，前台 live 默认模型为 `deepseek-ai/DeepSeek-V4-Flash`；高质量/复核模型规划使用 `Qwen/Qwen3.6-35B-A3B`，不进入默认实时链路。

DeepSeek API 仍保留同协议 provider 接口，用于对照和备份。

## 当前已部署或已接入

| 层级 | 名称 | 类型 | 当前状态 | 作用 | 备注 |
| --- | --- | --- | --- | --- | --- |
| Document Parser | MinerU local `3.1.15` | PDF parsing / OCR / layout engine | 已本地部署并完成 95/95 registered documents 可检索治理；失败 PDF 已通过 raster/OCR fallback 或 runtime/model 修复恢复 | PDF -> MinerU artifact | 通过 `127.0.0.1:8000` 调用；未来公网服务端自托管，不使用天翼云 |
| Vector Store | Qdrant `1.18.0` | Vector database | 已本地部署并完成 semantic live collection 全量重建 | 存储 `rag_chunk`、`table_record`、`evidence_record` | live collection `enzyme_immobilization_literature_sentence_baai_bge_base_en_v1_5_768_point_schema_v1` 当前 8263 points；hash baseline `enzyme_immobilization_literature` 和历史 `enzyme_immobilization_b10` 只作为 rollback 保留 |
| Embedding | `BAAI/bge-base-en-v1.5` | Sentence embedding | 已接入并设为默认 runtime | 语义召回和检索 | 768 维，`local_files_only: true` |
| Evidence Extraction | Rule-based extractor | 规则抽取器 | 已接入 | 从 RAG 原料层抽取 enzyme/carrier/condition/metric/table row | 不是 LLM；输出 first-pass evidence 和 review queue |
| Stream UX | NDJSON stream | Frontend/API streaming | 已接入 | Web 工作台逐步展示 retrieval / delta / final | 保留 JSON 接口兼容 CLI 和脚本 |

## 后续计划接入

| 层级 | 推荐选择 | 类型 | 优先级 | 作用 | 边界 |
| --- | --- | --- | --- | --- | --- |
| Generator LLM | SiliconFlow API `deepseek-ai/DeepSeek-V4-Flash` | Live Chat / generation LLM | 已接入 | 生成推荐固化剂、优化配方、解释证据和不确定性 | 前台 live 默认模型；已接入 streaming；不把 API key 写入仓库 |
| Review LLM | SiliconFlow API `Qwen/Qwen3.6-35B-A3B` | 高质量/复核 LLM | 规划中 | 对 live 答案做证据一致性、遗漏风险、citation 覆盖和实验边界复核 | 不阻塞 live 首答；以异步复核或手动复核模式进入 |
| Generator LLM | DeepSeek API | Chat / generation LLM | P0 | 保留生成式 LLM 备用 provider 接口 | 与 SiliconFlow 共用 generator protocol；可用于成本、可用性、效果对照 |
| Scientific Embedding | BGE-M3 或同等级中英科学文本 embedding | Embedding model | P1 | 替换当前 `bge-base-en-v1.5`，提升语义召回 | 替换 embedding backend，不改 Qdrant payload contract |
| Reranker | BGE reranker 或 LLM rerank | Cross-encoder / reranking | P1 | 对 top-k evidence 排序，降低噪音 | 先在小规模 curated evidence 上评估，再进入默认链路 |
| Extraction LLM | SiliconFlow 或本地小模型 | Structured extraction | P2 | 辅助 rule-based extractor 处理复杂段落/表格 | 必须输出 JSON，保留 source span 和 review flags |
| Formula Optimizer | Generator LLM + rules | Recommendation agent | P2 | 根据用户配方输出优化建议 | 必须基于 retrieval evidence，不允许无证据自由发挥 |

## MinerU 本地运行约束 260525

- `MINERU_DEVICE_MODE=cpu` 是当前本地 MinerU 默认配置，用于规避 MPS 下 `seal_PP-OCRv4_det_server_infer.pth` 权重 shape 与 server seal arch 不匹配的问题。
- `seal_lite` 权重已补齐；CPU 模式会走 lite seal OCR 分支，A47/A75 已通过原 PDF 重跑恢复。
- A34 曾出现 stale `running` job，但 MinerU result endpoint 已有 zip；已复用/恢复 artifact 并重新完成 RAG/evidence/Qdrant 入库。
- 当前 ingestion registry 口径：`searchable=95`；runtime dashboard 口径：`indexed_docs=95`、`indexed_pages=1004`、`qdrant_points=8263`、Qdrant green。

## Runtime 抽象方向

后续新增轻量 runtime 配置，不做复杂模型平台：

```yaml
document_parser:
  provider: mineru_local
  network_scope: self_hosted
  base_url: http://127.0.0.1:8000

vector_store:
  provider: qdrant
  url: http://127.0.0.1:6333
  collection: enzyme_immobilization_literature_sentence_baai_bge_base_en_v1_5_768_point_schema_v1

embedding:
  provider: sentence
  dimensions: 768
  model_name: BAAI/bge-base-en-v1.5
  local_files_only: true

reranker:
  provider: none

generator:
  provider: siliconflow
  model: deepseek-ai/DeepSeek-V4-Flash
  temperature: 0.1

generator_providers:
  siliconflow:
    enabled: true
    model: deepseek-ai/DeepSeek-V4-Flash
  siliconflow_review:
    enabled: true
    model: Qwen/Qwen3.6-35B-A3B
  deepseek:
    enabled: false
    model: TBD
```

Runtime 层只负责配置和工厂：

```text
runtime.document_parser
runtime.embedding_model
runtime.vector_store
runtime.retriever
runtime.generator
```

不做模型热加载、多租户、dashboard、权限系统。

## 高质量/复核模式开发规划

### 目标

前台 live 模型负责快速给出可用答案；高质量/复核模型负责二次审查，不抢首屏响应。复核结果必须围绕 evidence context 和原始 citations，不允许自由扩写成新的无证据建议。

### 推荐链路

1. Live generation：`deepseek-ai/DeepSeek-V4-Flash` 使用现有 `/api/recommend/by-enzyme/stream` 和 `/api/optimize/formulation/stream` 生成首答。
2. Review request：前端提供“高质量复核”按钮，或在 live final 后异步触发 `/api/review/recommendation/stream`。
3. Review context：后端传入用户 query、retrieval hits、live answer structured JSON、generation_content 和 citation mapping。
4. Review generation：`Qwen/Qwen3.6-35B-A3B` 输出严格 JSON：
   - `verdict`: `pass | revise | insufficient_evidence`
   - `citation_issues`: 缺失、错配、证据不足的 citation 列表
   - `scientific_risks`: 条件外推、载体/酶名混淆、指标不可比等风险
   - `recommended_revision`: 只基于已有 evidence 的修订候选
   - `human_review_required`: 高风险时强制为 `true`
5. UI render：复核结果以独立 panel 展示，不覆盖 live 答案；只有用户点击“采用复核修订”才替换候选。

### 后端实现阶段

P0:

- 在 `RuntimeServices` 增加 `generator(provider_name: str | None = None)` 或新增 `review_generator()`，默认保持现有 `generator.provider` 行为不变。
- 新增 review schema：`ReviewRecommendationRequest`、`ReviewRecommendationResponse`。
- 新增 review service：复用 retrieval hits 和 live structured response，不重新检索，避免复核结果和首答证据集漂移。
- 新增接口：`POST /api/review/recommendation/stream`，NDJSON event 与现有 stream 兼容。

P1:

- 前端新增“高质量复核”模式入口：live final 后按钮可用；复核中显示 reasoning/progress，但不把 `reasoning_content` 当最终答案。
- 将复核 verdict、citation issues、recommended revision 渲染成可对照卡片。
- 增加超时与取消：复核模型默认 300s；用户可取消，不影响 live 答案。

P2:

- 记录 review artifacts 到 `artifacts/reviews/`，用于后续人工审核和 prompt 迭代。
- 增加离线 benchmark：同一批 curated queries 对 live answer 与 reviewed answer 做 citation coverage、unsupported claim count、latency 统计。

### 验证标准

- live TTFT 不因复核模式增加而变慢。
- 复核模型不能生成无 citation 的新增候选。
- 对已知 citation 错配样例，复核必须标出 `human_review_required=true`。
- 前端在复核超时、取消、模型错误时仍保留 live 答案。
