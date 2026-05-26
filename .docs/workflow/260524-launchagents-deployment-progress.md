# LaunchAgents Persistent Deployment Progress

## 现状分析

本轮目标是把本地四个核心服务用 macOS LaunchAgents 做持久化部署，并加入集中日志管理：

- Qdrant: `127.0.0.1:6333/6334`
- MinerU API: `127.0.0.1:8000`
- FastAPI backend: `127.0.0.1:8001`
- Static frontend: `127.0.0.1:5173`
- 日志目录: `~/Library/Logs/Shengji/`

当前代码层面的部署资产已经落在 `deploy/local/`，与业务代码、RAG 代码、前端代码保持剥离。最终部署采用 runtime mirror，运行目录为 `~/Library/Application Support/Shengji/app`，LaunchAgents 执行 `~/Library/Application Support/Shengji/bin` 下的安装期生成 wrappers，避免 launchd 直接访问 `Desktop` / `Documents` 触发 macOS TCC 限制。

Qdrant 正式 collection 已通过全量重建切到 `enzyme_immobilization_literature`。
历史 `enzyme_immobilization_b10` 保留为 rollback collection，不删除。

## 已完成

- 新增 LaunchAgents 本地部署目录 `deploy/local/`。
- 新增四个服务 runner：
  - `deploy/local/bin/run_qdrant.sh`
  - `deploy/local/bin/run_mineru.sh`
  - `deploy/local/bin/run_api.sh`
  - `deploy/local/bin/run_web.sh`
- 新增日志管理脚本：
  - `deploy/local/bin/logs.sh`
  - `deploy/local/bin/rotate_logs.sh`
- 新增生命周期脚本：
  - `deploy/local/install_launchagents.sh`
  - `deploy/local/uninstall_launchagents.sh`
  - `deploy/local/restart_launchagents.sh`
  - `deploy/local/status_launchagents.sh`
  - `deploy/local/bin/check_ports.sh`
- 新增 plist templates：
  - `deploy/local/launchd/com.shengji.qdrant.plist.template`
  - `deploy/local/launchd/com.shengji.mineru.plist.template`
  - `deploy/local/launchd/com.shengji.api.plist.template`
  - `deploy/local/launchd/com.shengji.web.plist.template`
  - `deploy/local/launchd/com.shengji.logrotate.plist.template`
- 新增本地配置样例 `deploy/local/env.example`。
- `.gitignore` 已忽略 `deploy/local/env.local`，避免本地 secret 或端口覆盖配置入库。
- 新增工程文档 `.docs/engineering/local_launchagents_deployment.md`，记录 LaunchAgents、日志、Qdrant 数据治理和 Docker 边界。
- 安装脚本已同步 runtime mirror 到 `~/Library/Application Support/Shengji/app`。
- LaunchAgents 已成功启动四个业务服务和一个 logrotate job。
- 本地 smoke 默认使用 `hash_v1` embedding 与 `mock` generator，避免 Hugging Face cache/proxy 和外部 LLM key 成为部署阻塞。

## 已验证

静态验证通过：

```bash
bash -n deploy/local/*.sh deploy/local/bin/*.sh
plutil -lint deploy/local/launchd/*.plist.template
```

渲染后的 plist 也已在临时目录做过 `plutil -lint`，语法有效。

安装前端口检查通过：

```bash
deploy/local/bin/check_ports.sh
```

最终验证：

```text
API health: status=ok, generator_provider=mock, vector_store=qdrant
Qdrant collection: status=green, points_count=2508, vector_size=768
Frontend: GET / 返回工作台 HTML
Recommendation smoke: POST /api/recommend/by-enzyme 返回 recommendation_id、evidence_hits、citations
Tests: 9 passed
```

## 已解决阻塞

首次执行 `deploy/local/install_launchagents.sh` 后，五个 LaunchAgent 曾进入失败状态：

```text
last exit code = 126
```

服务 health check 均不可用：

- Qdrant: `http://127.0.0.1:6333/collections`
- MinerU: `http://127.0.0.1:8000/health`
- API: `http://127.0.0.1:8001/api/health`
- Web: `http://127.0.0.1:5173/`

集中日志显示：

```text
shell-init: error retrieving current directory: getcwd: cannot access parent directories: Operation not permitted
/bin/bash: /Users/way/Documents/生机大模型/deploy/local/bin/run_api.sh: Operation not permitted
```

同类错误出现在 qdrant、mineru、api、web、logrotate。

## 已定位线索

不是脚本缺少执行位；`deploy/local/bin/*.sh` 已经是 executable。

关键原因指向 macOS LaunchAgent 与 `~/Documents` 的 TCC/权限边界：

- 当前项目路径位于 `/Users/way/Documents/生机大模型`。
- plist 里设置了 `WorkingDirectory` 为项目目录。
- plist 直接把项目内脚本作为 `/bin/bash` 的第二个参数。
- LaunchAgent 直接执行项目脚本时被系统拒绝，返回 `Operation not permitted`。

临时诊断结果：

- LaunchAgent 不设置 `WorkingDirectory`，通过 `/bin/bash -lc` 先 `cd '/Users/way/Documents/生机大模型'` 后执行 `pwd && ls deploy/local/bin/run_api.sh` 可以成功。
- LaunchAgent 直接执行 `/Users/way/Documents/生机大模型/deploy/local/bin/check_ports.sh` 仍会 `Operation not permitted`。

因此，当前更像是 launchd 对“直接执行 Documents 下脚本”和 `WorkingDirectory` 的组合不友好，而不是整个项目目录完全不可读。

## 当前 runtime 状态

已执行：

```bash
deploy/local/install_launchagents.sh
```

运行态：

```text
com.shengji.qdrant    running
com.shengji.mineru    running
com.shengji.api       running
com.shengji.web       running
com.shengji.logrotate last exit code = 0
```

监听端口：

```text
6333 / 6334 / 8000 / 8001 / 5173
```

Codex 沙箱内通用 `curl` 会对部分本机 TCP 报 `Operation not permitted`，因此 `status_launchagents.sh` 已增加 `lsof` fallback；用户在普通 Terminal 中应以 HTTP health 为准。

## 剩余风险

- 当前 generator 已使用 `siliconflow`，需要本机 `.env.local` 提供 `SILICONFLOW_API_KEY`。
- 当前 embedding 为 `hash_v1` 768，适合离线 smoke；科学语义召回质量需要后续切回已缓存的 BGE/BGE-M3 或领域 embedding，并重建 Qdrant collection。
- `enzyme_immobilization_literature` 已完成正式重建，当前覆盖 76/95 unique documents；19 篇 MinerU 失败 PDF 需要后续 repair/OCR fallback 或 MinerU runtime/model cache 修复。

## 验证标准

- `launchctl print gui/$UID/com.shengji.*` 不再出现 `exit 126`。
- [x] `launchctl print gui/$UID/com.shengji.*` 不再出现 `exit 126`。
- [x] Qdrant collection endpoint 可访问。
- [x] MinerU 端口 `8000` 已监听，日志显示 Uvicorn running。
- [x] Backend `/api/health` 可访问。
- [x] Frontend `http://127.0.0.1:5173/` 可访问。
- [x] `~/Library/Logs/Shengji/` 有按服务拆分的 stdout/stderr log。
- [x] Qdrant runtime mirror 使用正式 collection `enzyme_immobilization_literature`，旧 `enzyme_immobilization_b10` 保留为 rollback。

等待阿伟验收后，可将该 workflow 移动到 `.docs/workflow/done/` 并从 `.docs/index.md` 活跃任务池移除。
