# MinerU 单篇 PDF Smoke Test

## 现状分析

项目已迁移到 `/Users/way/Desktop/99-生机大模型`。当前有 MOF 固定化脂肪酶论文资料目录，但该目录属于原始/外部数据，不进入 git。

已建立：

- enzyme immobilization MVP schema
- MinerU API 调用契约文档
- Pydantic validation
- MinerUClient

## 工程方案

本阶段目标是用一篇 PDF 打穿：

```text
PDF -> MinerU submit -> task_id -> result artifact -> artifact structure analysis -> extraction 输入选择
```

选定 smoke test PDF：

```text
MOF固定化脂肪酶文献调研/B10.pdf
```

Excel metadata 对应题目：

```text
Hierarchical ZIF-8 toward Immobilizing Burkholderia cepacia Lipase for Application in Biodiesel Preparation
```

选择理由：

- 覆盖 MOF/ZIF-8、lipase immobilization、biodiesel application。
- 论文体积约 3.7 MB，适合首轮 smoke test。
- 预期包含固定化条件、应用指标和表格/图示，对后续 evidence extraction 有代表性。

## 风险

- MinerU 提交 endpoint 可能返回 5xx，属于服务端或网络环境问题。
- 结果获取 endpoint 与提交 endpoint 使用不同 host/port，必须分开配置。
- Artifact 可能是 zip，也可能是 JSON 状态，需要 client 层兼容。
- PDF 和解析产物不得进入 git。

## TODO

- [x] 选择单篇 smoke test PDF。
- [x] 增加 `scripts/run_mineru_smoke.py`。
- [x] 增加 `scripts/analyze_mineru_artifact.py`。
- [x] 本地部署 MinerU 3.1.15。
- [x] 真实调用本地 MinerU 获得 artifact。
- [x] 分析 md/content_list/middle_json/table 哪个最适合 extraction。
- [x] 形成第一版 extraction 输入策略。

## 执行结果

内网天翼云 MinerU 提交曾返回：

```text
POST http://220.154.141.69:8002/tasks
-> 502 Bad Gateway
```

已改为本地部署 MinerU：

```text
MinerU version: 3.1.15
API: http://127.0.0.1:8000
Task ID: da1f51e1-650e-49ad-bc4b-0db6c79ce71e
Status: completed
PDF pages: 14
Result type: application/zip
Result size: 687 KB
```

Artifact 已落地到 `artifacts/mineru_local_smoke/...`，该目录被 `.gitignore` 排除，不进入 git。

## Artifact 结构

解压后核心文件：

```text
B10.md
B10_content_list.json
B10_content_list_v2.json
B10_middle.json
B10_model.json
images/*.jpg
```

统计：

```text
markdown: 1
content_list: 2
middle_json: 1
model_json: 1
images: 31
content_list items: 131
content_list_v2 pages: 14
tables: 2
charts: 14
equations: 6
```

## Extraction 输入策略

推荐主输入：

```text
B10_content_list.json
```

理由：

- 每个 block 有 `type`、`page_idx`、`bbox`，适合 evidence traceability。
- table block 保留 `table_body` HTML，适合抽取 biodiesel yield、reusability、operating conditions。
- text block 可直接定位 enzyme、carrier、method、conditions、metric 片段。

辅助输入：

```text
B10.md
```

用于人工快速浏览和 LLM 上下文压缩。Markdown 可读性最好，但 page/bbox 追溯弱，不应作为唯一 evidence source。

追溯/调试输入：

```text
B10_middle.json
B10_model.json
images/
```

`middle_json` 体积大，保留详细 layout/span 信息，适合定位 OCR/版面问题，不适合直接喂给 extraction prompt。`images` 用于表格/图示复核。

## RAG 原料层

已新增：

```text
scripts/build_rag_inputs.py
src/enzyme_recommender/rag/artifacts.py
src/enzyme_recommender/rag/chunking.py
```

B10 smoke test 生成命令：

```bash
.venv/bin/python scripts/build_rag_inputs.py \
  --artifact-dir artifacts/mineru_local_smoke/B10_da1f51e1-650e-49ad-bc4b-0db6c79ce71e/unpacked/B10/auto \
  --output-dir artifacts/rag_inputs/B10 \
  --source-pdf B10.pdf \
  --document-id B10
```

输出：

```text
document_manifest.json
rag_chunks.jsonl
table_records.jsonl
extraction_candidates.jsonl
```

B10 当前统计：

```text
content_items: 131
pages: 14
text_blocks: 69
rag_chunks: 36
text_chunks: 34
table_chunks: 2
table_records: 2
extraction_candidates: 34
```

策略：

- `rag_chunks.jsonl` 作为向量库主输入，保留 `source_pdf`、`page_start/page_end`、`bbox`、`section`、`source_block_indices`。
- `table_records.jsonl` 单独保存表格结构，包括 `columns`、`rows`、`html`、`caption`、`img_path`。
- `extraction_candidates.jsonl` 只做 evidence extraction 候选，不直接当最终 evidence。
- 低价值短 chunk 会被过滤；表格也会镜像成 table chunk 进入 RAG 检索。
- `quality_flags` 已覆盖 `suspicious_percent_gt_300`、`suspicious_table_yield_gt_100`、`suspicious_reference_cell`、`possible_ocr_duplicate_text`。

重要发现：

- Abstract 中 `1279%` 被标记为 `suspicious_percent_gt_300`，后续不能直接进入 ranking。
- Table 1 中 `Yield (%) = 900.00` 被标记为 `suspicious_table_yield_gt_100`。
- OCR 重复文本仍然存在，例如部分 activity recovery 段落，需要后续 evidence extraction 阶段进入 review queue。

## 关键工程发现

- 本地 MinerU 首次运行会下载模型文件并初始化 DocAnalysis，耗时明显；后续同类 PDF 会快很多。
- `httpx` 默认读取系统 proxy 环境变量，本地 `127.0.0.1` 请求可能被代理导致 `502`。`MinerUClient` 必须使用 `trust_env=False`。
- `/tasks/{task_id}/result` 返回 zip；client 应保存 zip 后再解压，避免直接把大 JSON 混进业务流程。

## 验证标准

- [x] artifact 目录含 manifest，记录 PDF sha256、task_id、MinerU options 和 result artifact。
- [x] 能列出 artifact 中 md/content_list/middle_json/table/image 的文件数量。
- [x] 能判断 extraction 首选输入和辅助输入。
- [x] git 状态中不包含 PDF 或 artifact。
- [x] 能从 MinerU artifact 生成 RAG 原料层 JSONL。
- [x] RAG 原料层能保留 page/bbox/source block provenance。
- [x] 明显异常数值能进入 quality flags。
