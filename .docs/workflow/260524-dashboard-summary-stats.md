# Dashboard Summary Stats Fix

## 现状分析

首页 `PDF 切片引擎` 卡片里的 `27 docs / 323 pages` 原本是前端硬编码，未连接 MinerU artifact、RAG inputs 或 Qdrant collection。后续正式 collection 已全量重建到 `enzyme_immobilization_literature`，当前 dashboard 应从 API 聚合返回 `97 source PDFs / 76 indexed docs / 6910 points`，不能再回退到旧硬编码或历史 B10 统计。

仓库内原始 PDF 目录 `MOF固定化脂肪酶文献调研` 当前有 97 个 PDF；仓库 `artifacts/rag_inputs` 只有 B10，运行态 Qdrant 才是当前已索引文档的主要状态源。

## 工程方案

- 新增后端 dashboard summary API，统一返回 source PDFs、processed docs、pages、RAG chunks、table records、evidence records、Qdrant points。
- processed docs/pages 优先从 Qdrant payload 聚合；Qdrant 不可用时回退到本地 `artifacts/rag_inputs/*/document_manifest.json`。
- 前端卡片不再硬编码数字，启动时拉取 `/api/dashboard/summary` 并渲染。
- 保留现有 reference enrichment 和 Qdrant scroll 改动，不覆盖已有 dirty work。

## 风险

- Qdrant payload 如果缺失 `document_id` 或页码，只能统计 points，docs/pages 会回退到 artifacts 或显示未知。
- runtime mirror 若没有原始 PDF 目录，source PDF 总数可能为 0；processed docs 仍可由 Qdrant 统计。
- 正式 collection 已迁移为 `enzyme_immobilization_literature`；历史 `enzyme_immobilization_b10` 只作为 rollback。

## TODO

- [x] 实现 API 聚合逻辑与 response model。
- [x] 前端绑定动态指标。
- [x] 增加单元测试覆盖聚合和回退。
- [x] 运行 tests 与 HTTP sanity check。

## 完成记录

- `PDF 切片引擎` 卡片改为读取 `/api/dashboard/summary`，不再硬编码 `27 docs / 323 pages`。
- source PDF inventory 当前为 97 docs / 1064 pages，使用 `pypdf` 统计本地 PDF 页数。
- Qdrant evidence/indexed 层当前来自正式 collection：76 indexed docs / 800 indexed pages / 6910 points，不再混入旧 B10 或前端硬编码。
- LaunchAgents runtime mirror 已同步 `MOF固定化脂肪酶文献调研`，`/api/pdfs/B10.pdf` 可从持久化部署返回 PDF。

## 验证标准

- `/api/dashboard/summary` 返回 `processed_docs` 不再固定为 27。
- 首页 `PDF 切片引擎` 卡片展示 API 返回的 processed docs/pages。
- Qdrant 不可用时 API 仍能从本地 manifests 返回可解释状态，不导致首页崩溃。
