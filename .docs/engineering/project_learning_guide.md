# 项目学习指南：一周看懂生机大模型

## 1. 先用一句话理解这个项目

这不是一个普通的“问答网页”。

它的核心是一个 **evidence-first 文献知识系统**：把生物酶固定化相关 PDF 论文送入本地 MinerU 做解析，再把文本、表格和抽取出的 evidence 写入 Qdrant，最后由 FastAPI 把检索结果交给生成式 LLM，输出：

- 酶名推荐
- 配方优化
- 论文问答
- 证据检索

所以它本质上是：

```text
PDF 文献处理系统 + RAG 检索系统 + 证据抽取系统 + LLM 应用层 + Web 工作台
```

不是：

- 不是单纯前端 demo
- 不是只有一个聊天接口
- 不是传统 MySQL/Postgres 业务系统
- 不是通用多模态平台
- 不是完整的“图片语义理解”系统

## 2. 这个项目解决什么问题

项目目标是围绕 **生物酶固定化**，尤其是脂肪酶固定化文献，建立一个可追溯的智能助手。

它要回答的不是泛泛而谈的问题，而是类似：

- 某种 lipase 更适合什么 carrier 或 MOF？
- 某篇论文是怎么做固定化剂优化的？
- 当前 formulation 里的 pH、temperature、enzyme loading 怎么改更合理？
- 哪些结论来自具体哪篇论文哪一页？

这就是为什么项目把 “evidence” 放在系统中心，而不是先做一个大模型聊天壳。

## 3. 0 基础接手时，你必须先建立的正确抽象

### 3.1 这是一个五层系统

```text
前端展示层
-> FastAPI 服务层
-> 检索与推荐层
-> PDF ingestion / RAG / evidence 数据处理层
-> 本地运行时与存储层
```

### 3.2 论文问答、通用问答、酶名推荐，不是三套后端

前端看起来有多个模式，但后端核心入口高度复用。

大多数模式最后都走：

```text
POST /api/recommend/by-enzyme
POST /api/recommend/by-enzyme/stream
```

区别主要是：

- `objective` 不同
- `application_context` 不同
- 是否带 `document_id/source_pdf` 约束
- 是否走 document-scoped retrieval

也就是说，这个项目的“论文问答”不是独立 agent，而是同一个 recommendation/retrieval 系统在不同意图下的变体。

### 3.3 这个项目的“数据库”不是单一数据库

如果你带着传统 Web 项目的心智来找数据库，会马上走偏。

这里实际有三类存储：

- **原始事实层**：PDF、MinerU artifacts、RAG 输入、evidence 文件，主要在文件系统
- **流程状态层**：`artifacts/ingestion_registry/documents.jsonl` 和 `jobs.jsonl`
- **检索层**：Qdrant vector store

所以更准确地说，它是：

```text
文件系统 + JSONL registry + Qdrant
```

不是：

```text
前端 + FastAPI + MySQL
```

## 4. 先看目录，不然你会迷路

最重要的目录是这些：

```text
web/                          真实前端工作台
demo/leader_chat/             汇报型静态 demo，不是主运行链路
src/enzyme_recommender/       核心 Python 代码
scripts/                      启动、索引、benchmark、恢复、审计脚本
configs/                      runtime 配置
artifacts/                    ingestion、RAG、evidence、索引产物
MOF固定化脂肪酶文献调研/       原始 PDF 文献库
.docs/                        项目长期知识库
benchmarks/                   基准测试清单
tests/                        核心 contract / retrieval / runtime tests
deploy/local/                 macOS LaunchAgents 本地部署方案
```

建议第一次读仓库时，按这个顺序看：

1. `README.md`
2. `.docs/index.md`
3. `web/index.html`
4. `web/app.js`
5. `src/enzyme_recommender/api/app.py`
6. `src/enzyme_recommender/recommendation/enzyme.py`
7. `src/enzyme_recommender/rag/retrieval.py`
8. `src/enzyme_recommender/rag/chunking.py`
9. `src/enzyme_recommender/evidence/extractor.py`
10. `src/enzyme_recommender/ingestion/pipeline.py`

## 5. 系统总图：从 PDF 到答案

你可以把整条链路记成下面这张脑图：

```text
原始 PDF
-> MinerU 解析
-> content_list / markdown / images / middle_json
-> 文本块与表格块切分
-> rag_chunks / table_records / extraction_candidates
-> evidence_records / review_queue
-> Qdrant points
-> retrieval
-> LLM generation
-> 前端流式展示
```

更细一点：

```text
用户在前端输入问题
-> web/app.js 组装 payload
-> FastAPI route 收到请求
-> RecommendationService / FormulationOptimizationService 构建 retrieval query
-> EvidenceRetriever 去 Qdrant 查 point
-> 命中结果补齐本地 reference text
-> generator provider 调 SiliconFlow 或 mock
-> 返回 JSON 或 NDJSON stream
-> 前端逐步渲染 retrieval / delta / final
```

## 6. 前端：你看到的页面是怎么工作的

### 6.1 前端技术形态

主前端是纯静态页面，不是 React、Vue、Next.js。

核心文件：

```text
web/index.html
web/app.js
web/styles.css
```

这意味着：

- 学习成本低
- 调试直观
- 没有复杂的构建系统
- 前端状态逻辑基本都在 `web/app.js`

### 6.2 前端提供了哪些模式

前端模式在 `web/app.js` 里定义，主要有：

- `general`：通用问答
- `recommend`：酶名推荐
- `paper`：论文问答
- `optimize`：配方优化
- `search`：证据检索

这些模式不是切换不同后端应用，而是切换不同 payload 生成策略。

### 6.3 前端最关键的职责

前端的真实职责不是“做推理”，而是：

- 收集用户输入
- 判断当前 mode
- 构造请求 payload
- 调用 stream 或 JSON API
- 展示 evidence、citation、状态和错误
- 在论文问答模式下加载 document catalog 让用户选文献

### 6.4 前端与后端的连接方式

本地开发默认访问：

```text
http://127.0.0.1:8001
```

但 `web/index.html` 当前还预设了一个 Cloudflare tunnel 地址给 stream API，这说明它支持“静态前端公网部署，后端通过 tunnel 暴露”的演示模式。

`netlify.toml` 也说明了这一点：

- `web/` 会被 Netlify 发布
- `/api/*` 和 `/PDF/*` 会被转发到 Cloudflare tunnel

### 6.5 哪个前端是假的，哪个是真的

要分清楚：

- `web/`：主工作台，连真实 API
- `demo/leader_chat/`：汇报型 demo，使用本地样例数据，不调用真实 LLM

如果有人说“前端不是已经跑起来了吗”，你要先问他指的是 `web/` 还是 `demo/leader_chat/`。

## 7. 后端：FastAPI 做了什么

### 7.1 后端入口

主入口：

```text
src/enzyme_recommender/api/app.py
```

启动脚本：

```bash
scripts/start_api.sh
```

实际是用 `uvicorn` 起：

```text
enzyme_recommender.api.app:app
```

### 7.2 核心 API

最重要的接口是这些：

```text
GET  /api/health
GET  /api/dashboard/summary
GET  /api/documents

POST /api/recommend/by-enzyme
POST /api/recommend/by-enzyme/stream

POST /api/optimize/formulation
POST /api/optimize/formulation/stream

POST /api/search/evidence

GET  /api/ingestion/summary
POST /api/ingestion/uploads
POST /api/ingestion/uploads/raw
GET  /api/ingestion/batches/{batch_id}
GET  /api/ingestion/documents/{document_id}
POST /api/ingestion/documents/{document_id}/retry
POST /api/ingestion/documents/{document_id}/reindex

POST /api/evidence/{document_id}/{evidence_id}/curate
GET  /api/pdfs/{pdf_name}
```

### 7.3 后端的三个主职责

#### 第一类：应用入口

- 推荐
- 论文问答
- 配方优化
- 证据检索

#### 第二类：知识库运维入口

- 上传 PDF
- 查看 ingestion 状态
- 重试/重建索引
- 导出或查看文献目录

#### 第三类：展示辅助

- dashboard summary
- PDF 原文访问
- evidence 引用上下文补齐

### 7.4 stream 为什么重要

这个项目不是简单 `POST -> 等几秒 -> 一次性返回`。

它支持 NDJSON stream，事件类型包括：

- `status`
- `retrieval`
- `delta`
- `final`
- `error`

这决定了：

- 前端能做更好的 live UX
- 能先展示检索状态，再展示答案
- 更适合接真实大模型

## 8. Runtime 配置：系统能力由什么开关控制

主配置文件：

```text
configs/local.yaml
```

它定义了 5 件事：

- 用哪个 PDF parser
- 用哪个 vector store
- 用哪个 embedding model
- retrieval 的默认参数
- 用哪个 generator provider

当前默认配置的关键点：

- PDF parser：本地 MinerU
- vector store：Qdrant
- embedding：`BAAI/bge-base-en-v1.5`
- generator：SiliconFlow
- live model：`deepseek-ai/DeepSeek-V4-Flash`

另外还有一个重要概念：

- `configs/local.hash.yaml` 是 hash rollback baseline
- `configs/local.yaml` 是当前 live semantic runtime

也就是说，检索层是可以回滚的。

## 9. 数据层 / 数据库：你必须把这一节看懂

### 9.1 这个项目没有传统意义上的业务数据库

仓库里没有 migration、ORM model、SQL schema 主链路。

这里的核心数据不在关系库，而在三层：

#### 原始数据层

```text
MOF固定化脂肪酶文献调研/*.pdf
artifacts/uploads/raw/*.pdf
```

#### 过程产物层

```text
artifacts/mineru/<document_id>/<task_id>/...
artifacts/rag_inputs/<document_id>/
artifacts/evidence/<document_id>/
artifacts/indexing/<collection>/<document_id>.json
```

#### 状态与检索层

```text
artifacts/ingestion_registry/documents.jsonl
artifacts/ingestion_registry/jobs.jsonl
Qdrant collection
```

### 9.2 JSONL registry 是干什么的

`documents.jsonl` 记录每篇文献当前处于什么状态，例如：

- `uploaded`
- `mineru_succeeded`
- `rag_built`
- `evidence_extracted`
- `indexed`
- `searchable`
- `needs_review`

`jobs.jsonl` 记录每次 ingestion job 执行到了哪一步，例如：

- `mineru_parse`
- `rag_build`
- `evidence_extract`
- `qdrant_index`
- `retrieval_verify`

所以它本质上是一个 **文件化状态机数据库**。

### 9.3 Qdrant 里存的不是“论文全文”，而是 point

Qdrant 里主要有三类 point：

- `rag_chunk`
- `table_record`
- `evidence_record`

这三类 point 的职责完全不同：

- `rag_chunk`：给上下文召回
- `table_record`：给表格级调试与召回
- `evidence_record`：给推荐、配方优化、证据问答优先使用

### 9.4 为什么这套设计合理

因为项目目标不是“把 PDF 存起来”，而是“把论文转成可检索、可引用、可审查的 evidence 系统”。

如果一开始就只做全文 embedding，后面的：

- 表格级质量控制
- evidence review
- curated overlay
- bad-table 排除
- no-answer gate

都会很难做。

## 10. 知识库：这个项目真正的核心

### 10.1 知识库不是 PDF 文件夹

很多人会误解知识库就是原始文献目录。不是。

这个项目的知识库应该分成四层：

```text
原始文献层
-> 解析产物层
-> RAG 原料层
-> evidence 层
```

### 10.2 四层分别是什么

#### 原始文献层

原始 PDF，主要在：

```text
MOF固定化脂肪酶文献调研/
```

#### 解析产物层

MinerU 解析出来的内容，例如：

- `content_list`
- `markdown`
- `middle_json`
- `images`

#### RAG 原料层

由 `build_rag_inputs()` 生成：

- `rag_chunks.jsonl`
- `table_records.jsonl`
- `extraction_candidates.jsonl`
- `document_manifest.json`

#### evidence 层

由规则抽取器生成：

- `evidence_records.jsonl`
- `review_queue.jsonl`
- `validation_report.json`

### 10.3 为什么要专门有 evidence 层

因为系统要回答的是“有证据支持的建议”，不是“看起来像对的话”。

evidence 层把文本和表格进一步抽象成结构化事实，例如：

- 酶名
- 载体
- 固定化方法
- pH
- 温度
- enzyme loading
- biodiesel yield
- reuse cycles

这样后续推荐和优化才能尽量 grounded。

## 11. PDF 识别：系统如何读论文

### 11.1 PDF 识别依赖谁

依赖本地 / 自托管 MinerU。

关键约束非常明确：

- 只允许本地或自托管 MinerU
- 不允许天翼云 MinerU 进入正式路径

相关代码和文档：

```text
src/enzyme_recommender/ingestion/mineru.py
.docs/research/mineru_pdf_ingestion_api.md
```

### 11.2 调用模式

MinerU 采用异步任务模式：

```text
POST /tasks
-> 返回 task_id
GET /tasks/{task_id}/result
-> 拉取 zip 或 JSON 结果
```

在项目中，`MinerUClient` 负责：

- 提交 PDF
- 记录 manifest
- 轮询结果
- 下载 zip
- 解压 artifact

### 11.3 MinerU 开了哪些能力

当前默认参数最关键的是：

- `table_enable=true`
- `return_content_list=true`
- `return_middle_json=true`
- `return_images=true`
- `image_analysis=false`

这说明：

- **表格结构识别是开启的**
- **图片文件返回是开启的**
- **图片语义分析没有开启**

这句话非常重要，后面讲“图片识别”时会回到这里。

### 11.4 PDF 识别之后产出什么

MinerU 不是直接产出“答案”，而是产出一组中间文件。

系统最依赖的是 `content_list`，因为后续 chunking 主要就是从这里读 block。

## 12. 切片：这个项目里的“切片”到底指什么

这里至少有两层“切片”概念，必须分清。

### 12.1 第一层：PDF 页面级切片

MinerU 解析时天然以 page 为单位处理，并在 block 里保留 `page_idx`。

这保证了：

- citation 能回到 PDF 页码
- placeholder page 能被标记
- table chunk 能追溯到具体页

### 12.2 第二层：RAG 语义切片

真正的业务“切片”发生在：

```text
src/enzyme_recommender/rag/chunking.py
```

它会把 MinerU 的 content item 分成：

- text blocks
- table records

然后再构建：

- text chunk
- table chunk
- extraction candidate

### 12.3 chunking 的关键逻辑

`build_rag_inputs()` 做的事情大致是：

1. 找到 MinerU `auto` 目录
2. 读取 `content_list`
3. 过滤 header/footer/page number
4. 保留 text/list/equation/table
5. 把 table 单独转成 `table_record`
6. 把 text block 聚合成 `rag_chunk`
7. 对 table 再镜像生成 `table chunk`
8. 生成 extraction candidates
9. 执行 QA gate

### 12.4 为什么 table 还要再镜像成 chunk

因为系统既需要：

- 结构化表格数据用于后续抽取
- 又需要表格文本化后的召回能力用于 retrieval

所以 table 会以两种形式存在：

- `table_record`
- `table chunk`

这是一种很实用的双表示设计。

## 13. 表格识别：项目里最成熟的数据理解模块之一

### 13.1 表格识别怎么来的

来源不是项目自己写的 table detector，而是 MinerU 的表格解析结果。

项目自己的工作是：

- 读取 MinerU 给出的 table body
- 解析 HTML table
- 转成 `columns + rows`
- 补充 caption、signals、quality flags

核心入口：

```text
src/enzyme_recommender/rag/chunking.py
```

### 13.2 表格识别后的数据结构

每个 `table_record` 大致会包含：

- `table_id`
- `document_id`
- `source_pdf`
- `page_idx`
- `columns`
- `rows`
- `caption`
- `text`
- `signals`
- `quality_flags`

### 13.3 表格质量控制很严格

表格不是解析出来就直接进入 ranking。

`src/enzyme_recommender/ingestion/qa.py` 会做 QA gate，例如检查：

- 空表
- header 可疑
- 行列过稀疏
- ragged rows
- 怀疑宽表/旋转表
- 怀疑 flattened table
- placeholder page overlap

一旦命中严重问题，会发生三件事：

- `requires_review=true`
- `usable_for_ranking=false`
- `qa_status=fail` 或 `warning`

### 13.4 表格是怎么进入 evidence 的

`src/enzyme_recommender/evidence/extractor.py` 会从 `table_record` 的每一行提取 evidence。

当前最典型的 record type 是：

- `table_comparison_row`

这一步会尝试从表格里读出：

- enzyme
- substrate
- operating conditions
- reaction system
- acyl acceptor
- yield
- reusability

### 13.5 这套表格链路为什么重要

因为生物酶固定化文献里很多关键信息并不在正文，而在表格里：

- 不同 carrier 对比
- 不同 loading / pH / temperature 对比
- yield/reusability/stability 对比

如果没有表格链路，这个项目的推荐质量会直接掉一大截。

## 14. 图片识别：要非常实事求是地理解当前状态

### 14.1 当前“图片识别”不是完整视觉理解

这是最容易被名字误导的地方。

当前系统里和图片有关的真实情况是：

- MinerU 会返回图片文件：`return_images=true`
- 但 `image_analysis=false`
- 项目没有独立 image embedding pipeline
- 项目没有 figure caption -> figure semantics 的完整抽取链路
- 项目没有“上传单张图片进行问答”的接口

所以更准确地说，当前系统具备的是：

- **图片提取能力**
- **图片作为 PDF 解析副产物的保存能力**

而不是：

- 完整图片语义识别
- 图像问答
- 图表视觉检索

### 14.2 当前图片在哪些场景有价值

虽然没有图像语义理解，但图片仍然有用：

- 人工复核时回看论文页面
- 追溯表格和 figure 来源
- 为后续 figure-level QA 或视觉增强留接口

### 14.3 如果以后要补全图片识别，缺什么

至少还缺：

- figure block 的结构化建模
- OCR/figure caption 对齐
- image embedding 或 VLM 调用
- `figure_record` 这类 point_type
- figure-level QA 与 ranking 边界

所以如果有人说“项目已经支持图片识别”，你要纠正成：

```text
当前支持 PDF 图片产物保留，不支持完整图片语义理解
```

## 15. Evidence 抽取：这是系统的第二个核心

### 15.1 它不是 LLM 抽取器

当前 evidence extractor 是 **rule-based extractor**，不是大模型抽取。

入口：

```text
src/enzyme_recommender/evidence/extractor.py
```

这点非常关键，因为它决定了系统的工程风格：

- 更可控
- 更稳定
- 可批处理
- 可审计
- 但 recall 和泛化能力有限

### 15.2 抽取器主要抽什么

从 text chunk 和 table row 中抽：

- `enzyme_identity`
- `immobilization_strategy`
- `formulation_condition`
- `performance_metric`
- `table_comparison_row`

### 15.3 evidence 的结构为什么重要

每条 evidence 不只是 text，还会带：

- `record_type`
- `document_id`
- `source_pdf`
- `source_id`
- `citation`
- `metrics`
- `quality_flags`
- `review_reasons`
- `requires_review`
- `usable_for_ranking`

这就是为什么它能支撑：

- grounding
- ranking exclusion
- manual review
- curated overlay

### 15.4 evidence 不是不可更改的

项目专门设计了人工复核回灌：

```text
artifacts/evidence/<doc>/curation_decisions.jsonl
-> curated_evidence_records.jsonl
-> Qdrant evidence_record(candidate_source=curated_evidence)
```

也就是说，人工复核不会直接篡改原始 evidence，而是通过 overlay 叠加。

这是很正确的 data governance 设计。

## 16. 检索与推荐：问题是怎么变成答案的

### 16.1 RecommendationService 是主入口

主入口：

```text
src/enzyme_recommender/recommendation/enzyme.py
```

它负责：

- 识别 query intent
- 生成 retrieval query
- 决定是否 no-answer
- 调用 retriever
- 调用 generator
- 拼装最终 response

### 16.2 检索不是“向量搜一下就完了”

检索层实际做了很多事情：

- query planning
- intent routing
- record_type-aware recall
- lexical + dense hybrid signal
- numeric overlap
- table intent boost
- diversity penalty
- bad-table / placeholder exclusion

这说明项目已经不是“最初级 RAG demo”，而是在认真做 retrieval engineering。

### 16.3 no-answer guard 很重要

系统会主动拦截：

- 低信息问题
- 明显噪音
- prompt injection
- out-of-domain 类问题

这保证它不会为了“显得聪明”而胡答。

### 16.4 配方优化为什么单独有一套 service

入口：

```text
src/enzyme_recommender/recommendation/formulation.py
```

它和推荐共享 retrieval 基础设施，但目标不同：

- 推荐更偏“哪种 carrier / 方法更合适”
- 配方优化更偏“字段级 current -> recommended 修改”

它会把 `user_formulation` 也纳入 retrieval query，检索量比普通推荐更大，然后再从 hits 中挑出更适合 formulation 的 evidence。

## 17. 文档问答：为什么它本质上还是 recommendation

论文问答模式并没有新建一个文档 QA 引擎。

它的核心思想是：

- 前端允许选择一篇或多篇论文
- 约束条件里塞入 `document_id` / `source_pdf`
- retrieval 变成 document-scoped
- objective 变成 `answer_paper_process_question`

这是一种非常务实的设计：

- 少一套系统
- 多复用一套 retrieval
- 更容易维护

但代价是：

- 如果 objective/prompt 没设计好，普通问答和论文问答容易串味

项目文档里已经专门记录过这个问题，并做了纠偏。

## 18. PDF ingestion：新文献怎么进入系统

### 18.1 这不是“上传成功就入库”

这是项目最重要的 data governance 规则之一。

一篇 PDF 只有走完：

```text
upload
-> mineru
-> rag_build
-> evidence_extract
-> qdrant_index
-> retrieval_verify
-> searchable / needs_review
```

才算真正进入知识库。

### 18.2 管线主入口

核心代码：

```text
src/enzyme_recommender/ingestion/pipeline.py
src/enzyme_recommender/ingestion/registry.py
src/enzyme_recommender/ingestion/state_machine.py
scripts/run_ingestion_worker.py
```

### 18.3 状态机为什么重要

因为 PDF 处理天然会失败：

- PDF 损坏
- MinerU 异常
- 表格坏掉
- evidence 抽取失败
- Qdrant 写入失败
- retrieval 验证失败

如果没有状态机，你就只能靠日志找尸体。

现在这套状态机至少让每篇 PDF 都有：

- 当前状态
- 最新 job
- 错误阶段
- 错误信息
- 可恢复点

### 18.4 为什么有 fallback / repair

真实文献 PDF 很脏，不是每篇都能一次成功解析。

项目里已经专门预留了：

- raster fallback
- PDF repair
- reindex only
- gap audit

这说明作者已经从 demo 阶段进入了“做长期文献处理系统”的思路。

## 19. 人工复核：为什么这是必须的

这个项目并不假装 OCR 和规则抽取永远正确。

它明确承认：

- bad table 会出现
- OCR 重复会出现
- enzyme 名缺失会出现
- 百分比异常会出现
- placeholder page 会出现

所以它设计了人工复核链路。

核心文档：

```text
.docs/engineering/manual_evidence_review.md
```

核心思路：

- 原始 evidence 不直接改
- 学生或研究人员先标注 CSV
- 再把人工决策导回 curated overlay
- curated overlay 进入 Qdrant

这非常适合科研场景，因为它保留了 audit trail。

## 20. 测试与 benchmark：项目不是靠感觉在迭代

### 20.1 tests 主要测什么

`tests/` 更像 contract 和回归保护层，重点测：

- runtime config
- collection / embedding contract
- citation/page 映射
- document resolver
- query planner
- no-answer guard
- 中文 enzyme alias 扩展

这意味着测试关注的是“系统行为边界”，不是 UI 像素级测试。

### 20.2 benchmarks 主要测什么

`benchmarks/` 里有几类清单：

- retrieval regression
- retrieval quality
- answer quality
- no-answer intent
- formulation optimizer

这是判断系统是不是“真的变好”，而不是“看起来还能用”的关键。

### 20.3 为什么 benchmark 很重要

因为这个项目做的是：

- 检索
- 结构化抽取
- 生成

任何一层稍微改一下，都可能出现 silent regression。

没有 benchmark，系统会很快变成靠演示样例活着。

## 21. 部署与运维：本地是怎么跑长期服务的

### 21.1 本地服务组成

本地长期服务主要有：

- Qdrant：6333/6334
- MinerU：8000
- FastAPI：8001
- ingestion-worker
- static web：5173

### 21.2 为什么用了 LaunchAgents

因为项目在 macOS 上长期运行，而且仓库放在 Desktop 下时，launchd 可能遇到 TCC 问题。

所以部署方案做了一层 runtime mirror：

```text
~/Library/Application Support/Shengji/app
```

这不是业务需求，而是本地运维层为 macOS 做的工程化处理。

### 21.3 公网演示怎么做

当前仓库里能看到一条演示路径：

- 前端部署到 Netlify
- 后端通过 Cloudflare quick tunnel 暴露

这说明项目已经在尝试“最小公网可演示架构”，但它不等于正式生产架构。

## 22. 哪些能力已经打通，哪些还没有

下面这张表最适合新人建立现实预期。

| 模块 | 当前状态 | 你应该怎么理解 |
| --- | --- | --- |
| 静态前端工作台 | 已打通 | 主入口在 `web/`，支持真实 API |
| FastAPI 后端 | 已打通 | 推荐、优化、搜索、ingestion、curation 都有接口 |
| Qdrant 检索 | 已打通 | 是当前主数据库之一 |
| JSONL registry | 已打通 | 承担 ingestion 状态机角色 |
| PDF 解析 | 已打通 | 依赖本地 MinerU |
| 文本切片 | 已打通 | `rag/chunking.py` 是核心 |
| 表格识别 | 已打通 | 基于 MinerU + 本地 HTML table 解析 |
| Evidence 抽取 | 已打通 | 当前是 rule-based，不是 LLM |
| 配方优化 | 已打通 | 与推荐共享 retrieval 基础设施 |
| 手工复核 overlay | 已打通 | 可回灌 curated evidence |
| 图片提取 | 部分打通 | MinerU 返回 images，但未做语义理解 |
| 图片语义识别 | 未打通 | 当前没有 figure-level/VLM pipeline |
| 独立多模态问答 | 未打通 | 没有图片上传问答接口 |
| 传统 SQL 业务库 | 没有 | 不是本项目主架构 |

## 23. 第一天就该跑什么

如果你要从 0 开始上手，第一天不要急着改代码，先把系统跑通。

建议顺序：

```bash
scripts/start_qdrant_local.sh
scripts/start_api.sh
python3 -m http.server 5173 -d web
```

然后检查：

```bash
curl http://127.0.0.1:8001/api/health
curl http://127.0.0.1:8001/api/dashboard/summary
```

最后浏览器打开：

```text
http://127.0.0.1:5173
```

你至少要确认四件事：

- 前端能打开
- API health 正常
- dashboard summary 有数据
- 发送一个 query 能收到 stream 或 JSON 响应

## 24. 一周学习计划：按这个节奏，能真正看懂系统

### Day 1：先把系统跑起来，不改代码

目标：

- 知道项目是干什么的
- 知道怎么启动前端和后端
- 知道主要目录在哪
- 知道 `web/` 和 `demo/leader_chat/` 的区别

必须完成：

- 跑通 `GET /api/health`
- 打开前端并发一条 query
- 阅读 `README.md` 和 `.docs/index.md`

### Day 2：看前端和 API 层

目标：

- 知道前端有哪些 mode
- 知道 mode 如何映射到 API
- 知道 stream 和 JSON 的区别

重点阅读：

- `web/index.html`
- `web/app.js`
- `src/enzyme_recommender/api/app.py`
- `src/enzyme_recommender/api/models.py`

你要回答得出：

- 论文问答为什么不算独立系统
- 配方优化 payload 和推荐 payload 差在哪

### Day 3：看 recommendation 和 retrieval

目标：

- 看懂 query 是怎么构造的
- 看懂 retrieval hit 为什么能带 citation
- 看懂 no-answer guard 为什么存在

重点阅读：

- `src/enzyme_recommender/recommendation/enzyme.py`
- `src/enzyme_recommender/recommendation/formulation.py`
- `src/enzyme_recommender/rag/retrieval.py`
- `src/enzyme_recommender/rag/query_guard.py`

你要回答得出：

- 为什么系统不是“查 top-k 然后喂 LLM”这么简单

### Day 4：看知识库与数据库

目标：

- 搞清楚 Qdrant、JSONL registry、artifacts 三者关系
- 搞清楚 point_type 和 record_type 的差异

重点阅读：

- `.docs/engineering/rag_retrieval_architecture.md`
- `.docs/engineering/data_governance_rag_boundaries.md`
- `src/enzyme_recommender/rag/qdrant.py`
- `src/enzyme_recommender/ingestion/registry.py`

你要回答得出：

- 为什么这个项目不需要先上 Postgres 才能工作

### Day 5：看 PDF ingestion、切片、表格识别

目标：

- 看懂文献是如何进入系统的
- 看懂 chunk/table/evidence 三层转换
- 看懂 QA gate 为什么必要

重点阅读：

- `src/enzyme_recommender/ingestion/mineru.py`
- `src/enzyme_recommender/ingestion/pipeline.py`
- `src/enzyme_recommender/ingestion/state_machine.py`
- `src/enzyme_recommender/rag/chunking.py`
- `src/enzyme_recommender/ingestion/qa.py`

你要回答得出：

- “切片”到底在什么代码里发生
- 坏表为什么不能直接进 ranking

### Day 6：看 evidence 抽取、人工复核、benchmark

目标：

- 看懂 evidence 是怎么抽出来的
- 看懂人工复核为什么不用直接改原始记录
- 看懂 benchmark 如何约束系统质量

重点阅读：

- `src/enzyme_recommender/evidence/extractor.py`
- `.docs/engineering/manual_evidence_review.md`
- `benchmarks/README.md`
- `tests/test_core_contracts.py`
- `tests/test_chinese_enzyme_aliases.py`

你要回答得出：

- 为什么这个项目比一般 demo 更接近真实科研系统

### Day 7：自己走一遍完整闭环

目标：

- 从一篇 PDF 出发，手动走完整条链路

建议操作：

1. 选择一篇熟悉的 PDF，例如 `B10.pdf`
2. 看它在 `artifacts/rag_inputs/B10/` 下的产物
3. 看它在 `artifacts/evidence/B10/` 下的 evidence
4. 用 `/api/search/evidence` 查一条证据
5. 在前端问一个与该文献相关的问题
6. 回到 evidence 和 citation 验证答案是否 grounded

做到这一步，你就真的入门了。

## 25. 新人最容易踩的坑

### 坑 1：把 demo 当主系统

错。

主系统是 `web/ + FastAPI + Qdrant + artifacts`。

### 坑 2：把通用问答和论文问答当两套后端

错。

它们共享 recommendation/retrieval 主链路。

### 坑 3：以为有传统数据库 schema 没找到

错。

这里主数据是文件系统 + JSONL + Qdrant。

### 坑 4：以为图片识别已经做完

错。

当前只有图片提取，没有完整图片语义理解。

### 坑 5：以为 PDF 上传后立刻可检索

错。

必须走完整 ingestion pipeline 才能变成 `searchable`。

### 坑 6：看到 evidence 就默认可信

错。

还要看：

- `quality_flags`
- `qa_status`
- `requires_review`
- `usable_for_ranking`

## 26. 如果你只有 30 分钟，最少要搞懂什么

如果时间极少，至少记住下面这 8 句话：

1. 这是一个围绕生物酶固定化文献的 evidence-first RAG 系统。
2. 前端主入口在 `web/`，不是 `demo/leader_chat/`。
3. 后端主入口在 `src/enzyme_recommender/api/app.py`。
4. 文献先走 MinerU，再走 chunking、evidence、Qdrant。
5. 数据库不是 MySQL，而是文件系统 + JSONL registry + Qdrant。
6. 论文问答和通用问答复用同一套 recommendation/retrieval 主链路。
7. 表格识别已经是系统核心能力之一。
8. 图片目前只有提取，没有完整语义识别。

## 27. 推荐的继续阅读

如果你已经看完本文，下一批最值得读的是：

- `.docs/engineering/rag_retrieval_architecture.md`
- `.docs/engineering/pdf_ingestion_data_governance.md`
- `.docs/engineering/manual_evidence_review.md`
- `.docs/engineering/model_runtime_registry.md`
- `.docs/engineering/qa_benchmark_strategy.md`

## 28. 最后的判断标准

判断你是否真的理解了这个系统，不是看你能不能复述“用了 RAG、用了大模型、用了 Qdrant”。

真正的标准是你能不能独立回答这 5 个问题：

1. 用户在前端切到“论文问答”时，后端到底发生了什么变化？
2. 一条 evidence 为什么有时能展示，但不能参与 ranking？
3. 为什么这个项目没有传统 SQL 数据库也能成立？
4. 表格识别是在哪一层完成的，质量控制又在哪一层完成？
5. 图片现在到底支持到了什么程度，没支持到什么程度？

如果这 5 个问题都能讲清楚，你就已经不是“0 了解的人”了。
