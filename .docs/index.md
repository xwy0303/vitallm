# 项目记忆索引

## 科研与数据契约 (Research Docs)

`research/enzyme_immobilization_mvp_schema.md` - 生物酶固定化推荐 MVP 的核心 schema、推荐输入输出契约与证据边界
`research/mineru_pdf_ingestion_api.md` - MinerU PDF 切片/解析 API 调用方式、参数契约和 pipeline 注意事项

## 工程架构契约 (Engineering Docs)

`engineering/model_runtime_registry.md` - 当前/计划接入的模型与引擎清单、MinerU 本地化约束、SiliconFlow/DeepSeek 生成 LLM 规划
`engineering/rag_retrieval_architecture.md` - RAG 向量检索 collection、payload、embedding 替换边界和 ranking 禁用规则

## 当前活跃任务池 (Active Workflows)

`workflow/260521-mineru-smoke-test.md` - MinerU 单篇 PDF smoke test、RAG 原料层与 evidence extraction 闭环

## 全局重要记忆 (Global Memory)

- 生物酶固定化推荐必须基于 objective、application context、evaluation metrics 和 evidence records；不能把“最佳固化剂”当作脱离条件的全局唯一答案。
- PDF parsing 只使用本地/自托管 MinerU；天翼云 MinerU 不进入后续 MVP、外网部署或生产调用路径。
- 主要生成 LLM 后续优先接 SiliconFlow API，同时保留 DeepSeek API provider 接口；当前先保留架构约束，不把 API key 写入仓库。
