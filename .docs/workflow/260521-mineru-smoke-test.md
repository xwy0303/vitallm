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

## 关键工程发现

- 本地 MinerU 首次运行会下载模型文件并初始化 DocAnalysis，耗时明显；后续同类 PDF 会快很多。
- `httpx` 默认读取系统 proxy 环境变量，本地 `127.0.0.1` 请求可能被代理导致 `502`。`MinerUClient` 必须使用 `trust_env=False`。
- `/tasks/{task_id}/result` 返回 zip；client 应保存 zip 后再解压，避免直接把大 JSON 混进业务流程。

## 验证标准

- [x] artifact 目录含 manifest，记录 PDF sha256、task_id、MinerU options 和 result artifact。
- [x] 能列出 artifact 中 md/content_list/middle_json/table/image 的文件数量。
- [x] 能判断 extraction 首选输入和辅助输入。
- [x] git 状态中不包含 PDF 或 artifact。
