# 项目记忆索引

## 科研与数据契约 (Research Docs)

`research/enzyme_immobilization_mvp_schema.md` - 生物酶固定化推荐 MVP 的核心 schema、推荐输入输出契约与证据边界
`research/mineru_pdf_ingestion_api.md` - MinerU PDF 切片/解析 API 调用方式、参数契约和 pipeline 注意事项

## 工程架构契约 (Engineering Docs)

`engineering/model_runtime_registry.md` - 当前/计划接入的模型与引擎清单、MinerU 本地化约束、SiliconFlow/DeepSeek 生成 LLM 规划
`engineering/rag_retrieval_architecture.md` - RAG 向量检索 collection、payload、embedding 替换边界和 ranking 禁用规则
`engineering/data_governance_rag_boundaries.md` - `data-dev` 与 `ai-backend` 的职责边界、冻结 contract、共享文件归属和 merge 顺序
`engineering/local_launchagents_deployment.md` - macOS LaunchAgents 本地持久化部署、日志管理、Qdrant 数据治理和 Docker 边界
`engineering/system_deployment_report_260524.md` - 本地持久化部署后的项目组织架构、部署流程、验证结果与剩余风险
`engineering/pdf_ingestion_data_governance.md` - PDF 上传/批处理自动进入 MinerU、RAG/evidence、Qdrant 和大模型 RAG 的数据治理流程
`engineering/manual_evidence_review.md` - 人工 evidence/table 复核包导出、学生复核 SOP、curated evidence overlay 回灌边界
`engineering/project_development_retrospective_260526.md` - 从项目启动到当前的完整问题、修复、优化、效果与剩余风险复盘
`engineering/qa_benchmark_strategy.md` - 脂肪酶固定化问答系统分层 benchmark、case schema、验收门槛和 seed baseline

## 当前活跃任务池 (Active Workflows)

`workflow/260521-mineru-smoke-test.md` - MinerU 单篇 PDF smoke test、RAG 原料层与 evidence extraction 闭环
`workflow/260524-launchagents-deployment-progress.md` - LaunchAgents 本地持久化部署实现进度、当前 TCC/权限阻塞与下一步修复路线
`workflow/260524-dashboard-summary-stats.md` - 首页 PDF 切片/证据链统计从硬编码改为动态聚合的修复任务
`workflow/260525-rag-pipeline-optimization.md` - PDF-MinerU-RAG-Qdrant 链路优化清单、版本契约、semantic embedding 与 benchmark 规划
`workflow/260526-qa-answerability-grounding.md` - QA seed 驱动的 no-answer gate、citation grounding、paper-level planner 修复

## 全局重要记忆 (Global Memory)

- 生物酶固定化推荐必须基于 objective、application context、evaluation metrics 和 evidence records；不能把“最佳固化剂”当作脱离条件的全局唯一答案。
- PDF parsing 只使用本地/自托管 MinerU；天翼云 MinerU 不进入后续 MVP、外网部署或生产调用路径。
- 主要生成 LLM 后续优先接 SiliconFlow API，同时保留 DeepSeek API provider 接口；当前先保留架构约束，不把 API key 写入仓库。
