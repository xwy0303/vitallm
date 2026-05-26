# 生机大模型本地部署与系统报告

## 结论

截至 2026-05-24，本地 macOS LaunchAgents 持久化部署已完成。四个核心服务均已由 launchd 托管：

- Qdrant: `127.0.0.1:6333/6334`
- MinerU API: `127.0.0.1:8000`
- FastAPI backend: `127.0.0.1:8001`
- Static frontend: `127.0.0.1:5173`

另有 `com.shengji.logrotate` 每日轮转 `~/Library/Logs/Shengji/` 下的服务日志。

> Superseded note, 2026-05-25：本报告中的 `enzyme_immobilization_b10` 是当时的历史 collection 状态。正式 collection 已通过 registry/artifacts 全量重建为 `enzyme_immobilization_literature`，当前 runtime/API/dashboard 均应以正式 collection 为准；B10 只作为 rollback 保留。

## 项目组织架构

```text
.
├── configs/
│   └── local.yaml                 # 本地 runtime config，无 secret
├── deploy/local/
│   ├── install_launchagents.sh     # 安装、同步 runtime、渲染 plist、bootstrap launchd
│   ├── status_launchagents.sh      # launchd 状态与 health/listen 检查
│   ├── restart_launchagents.sh     # 单服务或全量重启
│   ├── uninstall_launchagents.sh   # 卸载 LaunchAgents，不删 runtime data
│   ├── bin/                        # 仓库内维护的 runner、日志、端口检查脚本
│   └── launchd/                    # plist templates
├── src/enzyme_recommender/
│   ├── api/                        # FastAPI app 与请求/响应模型
│   ├── generators/                 # mock / OpenAI-compatible generator provider
│   ├── ingestion/                  # MinerU client
│   ├── rag/                        # embedding、Qdrant REST client、retrieval
│   ├── recommendation/             # recommendation / formulation services
│   └── runtime/                    # runtime config 与 service factory
├── scripts/                        # CLI、RAG indexing/search、MinerU pipeline
├── web/                            # 静态前端工作台
├── tests/                          # 核心 contract tests
└── .docs/                          # 项目记忆、架构与 workflow 文档
```

## 部署结构

为规避 macOS TCC 对 `Desktop` / `Documents` 下 LaunchAgent 直接访问的限制，部署采用 runtime mirror：

```text
~/Library/Application Support/Shengji/
├── app/                            # 从仓库同步出的运行目录
│   ├── src/
│   ├── web/
│   ├── configs/
│   ├── artifacts/
│   ├── .local/qdrant/
│   ├── .venv/
│   └── .venv-mineru/
└── bin/                            # 安装时生成的 launchd wrappers
    ├── run_qdrant.sh
    ├── run_mineru.sh
    ├── run_api.sh
    ├── run_web.sh
    └── rotate_logs.sh
```

LaunchAgents 位于：

```text
~/Library/LaunchAgents/com.shengji.qdrant.plist
~/Library/LaunchAgents/com.shengji.mineru.plist
~/Library/LaunchAgents/com.shengji.api.plist
~/Library/LaunchAgents/com.shengji.web.plist
~/Library/LaunchAgents/com.shengji.logrotate.plist
```

日志位于：

```text
~/Library/Logs/Shengji/
```

## Runtime 配置

当前 `configs/local.yaml` 使用本地可离线 smoke 配置：

- parser: `mineru_local`
- vector store: `qdrant`
- collection: `enzyme_immobilization_b10`
- embedding: `hash_v1`, `768` dimensions
- generator: `mock`

`SiliconFlow` 与 `DeepSeek` provider 仍保留在配置中。要启用真实 LLM 生成，需要设置本地 `.env.local` 中的 `SILICONFLOW_API_KEY`，并将 `generator.provider` 切回 `siliconflow`。

## 部署流程

安装或刷新部署：

```bash
deploy/local/install_launchagents.sh
```

查看状态：

```bash
deploy/local/status_launchagents.sh
```

查看日志：

```bash
deploy/local/bin/logs.sh api --tail 100
deploy/local/bin/logs.sh all --follow
```

重启服务：

```bash
deploy/local/restart_launchagents.sh api
deploy/local/restart_launchagents.sh all
```

卸载 LaunchAgents：

```bash
deploy/local/uninstall_launchagents.sh
```

卸载不会删除 runtime mirror、Qdrant storage、artifacts、PDF、日志或模型缓存。

## 验证结果

静态验证：

```text
bash -n deploy/local/*.sh deploy/local/bin/*.sh
plutil -lint deploy/local/launchd/*.template
```

单元测试：

```text
9 passed in 0.26s
```

运行态监听：

```text
qdrant  *:6333, *:6334
mineru  127.0.0.1:8000
api     127.0.0.1:8001
web     127.0.0.1:5173
```

API health：

```json
{
  "status": "ok",
  "generator_provider": "mock",
  "vector_store": "qdrant",
  "collection": "enzyme_immobilization_b10"
}
```

Qdrant collection：

```text
collection: enzyme_immobilization_b10
status: green
points_count: 2508
vector_size: 768
```

系统 smoke：

- `POST /api/recommend/by-enzyme` 返回 `recommendation_id`、`evidence_hits`、citations 和 mock generation。
- 静态前端 `GET /` 返回工作台 HTML。
- Browser 插件当前未提供 `iab` 会话，因此未完成可视化点击验证；前端可用性通过 HTTP 与 API smoke 闭环验证。

## 风险与后续任务

- 当前为本地离线部署，默认使用 `mock` generator。真实推荐文案需要启用 SiliconFlow/DeepSeek API key 后复测。
- 当前 embedding 切到 `hash_v1` 768 以避免 Hugging Face cache/proxy 阻塞；该模式适合部署 smoke，不代表最终科学语义召回质量。
- 本报告记录的是 2026-05-24 的历史状态。2026-05-25 已完成正式 collection 全量重建，后续新增 PDF ingestion 默认进入 `enzyme_immobilization_literature`。
- Codex 沙箱内通用 `curl` 可能被本机 TCP 权限限制影响；`status_launchagents.sh` 已增加端口监听 fallback。用户在普通 Terminal 中运行时应以 HTTP health 为准。
