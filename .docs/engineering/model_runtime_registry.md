# Model Runtime Registry

## 硬约束

PDF parsing 只使用自托管/本地 MinerU 服务。

天翼云 MinerU 不进入后续 MVP、外网部署或生产调用路径。此前天翼云 API 只作为历史调研来源保留，不作为可切换 provider。

后续会把整个服务部署到公网，外部用户通过自有服务接口调用；外部请求不得直连用户本机或内网 MinerU。

主要生成 LLM 后续优先使用 SiliconFlow API，同时保留 DeepSeek API 作为生成式 LLM provider 接口。当前先记录架构约束，暂不实现具体 client。

## 当前已部署或已接入

| 层级 | 名称 | 类型 | 当前状态 | 作用 | 备注 |
| --- | --- | --- | --- | --- | --- |
| Document Parser | MinerU local `3.1.15` | PDF parsing / OCR / layout engine | 已本地部署并完成 B10 smoke test | PDF -> MinerU artifact | 通过 `127.0.0.1:8000` 调用；未来公网服务端自托管，不使用天翼云 |
| Vector Store | Qdrant `1.18.0` | Vector database | 已本地部署并完成 B10 入库检索 | 存储 `rag_chunk`、`table_record`、`evidence_record` | 本地 collection `enzyme_immobilization_b10` 已验证 119 points |
| Embedding | `hash-v1-384` | Deterministic local embedding | 已接入 | 验证 indexing/search pipeline | 只用于工程 smoke test，不作为最终专业检索模型 |
| Evidence Extraction | Rule-based extractor | 规则抽取器 | 已接入 | 从 RAG 原料层抽取 enzyme/carrier/condition/metric/table row | 不是 LLM；输出 first-pass evidence 和 review queue |

## 后续计划接入

| 层级 | 推荐选择 | 类型 | 优先级 | 作用 | 边界 |
| --- | --- | --- | --- | --- | --- |
| Generator LLM | SiliconFlow API | Chat / generation LLM | P0 | 生成推荐固化剂、优化配方、解释证据和不确定性 | 默认生成服务商；先做 API adapter 和 prompt contract；不把 API key 写入仓库 |
| Generator LLM | DeepSeek API | Chat / generation LLM | P0 | 保留生成式 LLM 备用 provider 接口 | 与 SiliconFlow 共用 generator protocol；可用于成本、可用性、效果对照 |
| Scientific Embedding | BGE-M3 或同等级中英科学文本 embedding | Embedding model | P1 | 替换 `hash-v1-384`，提升语义召回 | 替换 embedding backend，不改 Qdrant payload contract |
| Reranker | BGE reranker 或 LLM rerank | Cross-encoder / reranking | P1 | 对 top-k evidence 排序，降低噪音 | 先在小规模 curated evidence 上评估，再进入默认链路 |
| Extraction LLM | SiliconFlow 或本地小模型 | Structured extraction | P2 | 辅助 rule-based extractor 处理复杂段落/表格 | 必须输出 JSON，保留 source span 和 review flags |
| Formula Optimizer | Generator LLM + rules | Recommendation agent | P2 | 根据用户配方输出优化建议 | 必须基于 retrieval evidence，不允许无证据自由发挥 |

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
  collection: enzyme_immobilization

embedding:
  provider: hash_v1
  dimensions: 384

reranker:
  provider: none

generator:
  provider: siliconflow
  model: TBD
  temperature: 0.1

generator_providers:
  siliconflow:
    enabled: true
    model: TBD
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
