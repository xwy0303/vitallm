# MinerU PDF Ingestion API

## 定位

本文记录后续论文 PDF 切片/解析要用的 MinerU 调用方式。原始 `.http.yaml` 来自外部文件，仅作为 API contract 样例；不得把其中的本地文件路径、历史 `task_id`、凭证或网络环境假设写入业务代码。

当前推荐路线是本机部署 MinerU，再通过 `127.0.0.1` 接本地 `mineru-api`，避免依赖内网天翼云服务。

## 调用模型

当前样例体现的是异步任务模式：

```text
POST /tasks
  -> 返回 task_id
GET /tasks/{task_id}/result
  -> 拉取解析结果
```

注意：样例中的提交 endpoint 和结果获取 endpoint 使用了不同 host/port。后续实现 pipeline 时必须把它们拆成独立配置：

```text
MINERU_SUBMIT_BASE_URL
MINERU_RESULT_BASE_URL
```

不要默认二者相同。

本地 MinerU 部署时，二者可以相同：

```text
MINERU_SUBMIT_BASE_URL=http://127.0.0.1:8000
MINERU_RESULT_BASE_URL=http://127.0.0.1:8000
```

## 本地部署

本机实测环境：

```text
Python: /opt/homebrew/bin/python3.12
MinerU: 3.1.15
Local API: http://127.0.0.1:8000
```

安装建议使用独立虚拟环境，避免污染主项目依赖：

```bash
/opt/homebrew/bin/python3.12 -m venv .venv-mineru
.venv-mineru/bin/python -m pip install --upgrade pip uv
.venv-mineru/bin/python -m uv pip install -U 'mineru[all]'
```

如果 Homebrew Python 的证书链导致 PyPI SSL 校验失败，可临时使用 `--trusted-host` 安装，但不要写入全局 pip 配置。

启动本地 API：

```bash
.venv-mineru/bin/mineru-api --host 127.0.0.1 --port 8000 --enable-vlm-preload false
```

可用性检查：

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/openapi.json
```

本地 API 暴露路径：

```text
GET /health
POST /tasks
GET /tasks/{task_id}
GET /tasks/{task_id}/result
POST /file_parse
```

重要实现细节：Python HTTP client 连接本地 MinerU 时必须禁用系统代理环境变量，例如 `httpx.Client(trust_env=False)`。否则 `127.0.0.1` 请求可能被代理劫持并返回 `502 Bad Gateway`。

## Submit Task

方法：

```text
POST {MINERU_SUBMIT_BASE_URL}/tasks
Content-Type: multipart/form-data
```

multipart fields：

```yaml
files:
  type: file
  required: true
  multiple: true
backend:
  value: pipeline
  type: text
lang_list:
  value: ch
  type: text
parse_method:
  value: auto
  type: text
formula_enable:
  value: "true"
  type: text
table_enable:
  value: "true"
  type: text
image_analysis:
  value: "false"
  type: text
return_md:
  value: "true"
  type: text
return_middle_json:
  value: "true"
  type: text
return_model_output:
  value: "true"
  type: text
return_content_list:
  value: "true"
  type: text
return_images:
  value: "true"
  type: text
response_format_zip:
  value: "true"
  type: text
start_page_id:
  value: "0"
  type: text
end_page_id:
  value: "999"
  type: text
```

## Result Fetch

方法：

```text
GET {MINERU_RESULT_BASE_URL}/tasks/{task_id}/result
```

路径参数：

```yaml
task_id:
  type: string
  required: true
```

## Pipeline 约束

- 论文 PDF ingestion 阶段必须保留原始 PDF 路径、文件 hash、提交时间、task_id、MinerU 参数和解析产物路径，用于 data provenance。
- `response_format_zip=true` 时，结果应按 zip artifact 处理；下载后解压到独立 task 目录，避免覆盖同名文件。
- `return_md=true`、`return_middle_json=true`、`return_content_list=true` 对后续 RAG 和结构化抽取都很关键，默认保留。
- `return_model_output=true` 可用于 debug，但如果体积过大，生产批处理可配置关闭。
- `return_images=true` 对表格/图示溯源有价值，但会增加存储体积；MVP 可以开启，后续按成本调整。
- `image_analysis=false` 表示不做图像语义分析；对于论文表格优先依赖 `table_enable=true` 的结构化结果。
- `start_page_id` 和 `end_page_id` 使用 0-based page id；批量调试时可以只跑前几页降低成本。
- 结果轮询必须设置 timeout、retry interval 和失败状态记录，不能无限等待。

## 推荐 MVP 默认参数

```yaml
backend: pipeline
lang_list: en
parse_method: auto
formula_enable: "true"
table_enable: "true"
image_analysis: "false"
return_md: "true"
return_middle_json: "true"
return_model_output: "false"
return_content_list: "true"
return_images: "true"
response_format_zip: "true"
start_page_id: "0"
end_page_id: "999"
```

说明：

- 生物酶论文大概率以英文为主，MVP 默认 `lang_list=en`；中文论文再切到 `ch` 或做语言自动配置。
- `return_model_output` 默认关闭，避免批量 ingestion 产物膨胀；debug 单篇论文时开启。

## 后续实现建议

实现一个独立 MinerU client，暴露三个能力：

```text
submit_pdfs(pdf_paths, options) -> task_id
fetch_result(task_id) -> artifact
poll_until_done(task_id, timeout, interval) -> artifact
```

业务 pipeline 不直接拼 HTTP 请求，统一通过 client 层处理：

- endpoint 配置；
- multipart 构造；
- task 状态记录；
- zip 下载与解压；
- 文件 hash 与 data provenance；
- 错误分类和 retry。

本地 smoke test 命令：

```bash
.venv/bin/python scripts/run_mineru_smoke.py \
  --pdf 'MOF固定化脂肪酶文献调研/B10.pdf' \
  --submit-base-url http://127.0.0.1:8000 \
  --result-base-url http://127.0.0.1:8000 \
  --artifact-root artifacts/mineru_local_smoke \
  --lang-list en \
  --return-model-output true
```
