# Cloudflare Pages + Cloudflare Quick Tunnel Demo Deploy

## 现状分析

- 前端静态资源位于 `web/`，入口为 `web/index.html`、`web/app.js`、`web/styles.css`。
- 本机 FastAPI 后端运行在 `http://127.0.0.1:8001`，`/api/health` 可用。
- Cloudflare quick tunnel 通过 LaunchAgent `com.shengji.cloudflared.quick` 暴露本机后端。
- Cloudflare Pages project `shengji-enzyme-rag-lab` 已创建，首个 deployment URL 为 `https://2dab5404.shengji-enzyme-rag-lab.pages.dev`。
- 当前已验证 deployment URL 为 `https://037c1070.shengji-enzyme-rag-lab.pages.dev`，production alias 为 `https://shengji-enzyme-rag-lab.pages.dev`。
- Netlify 站点 `shengji-enzyme-rag-lab` 仍保留历史记录，但因 usage limit 不再作为主发布入口。

## 工程方案

- 前端生产环境默认使用同源 API base：`API_BASE_URL=""`。
- Cloudflare Pages `_worker.js` 最初将 `/api/*` 与 `/PDF/*` proxy 到当时的
  Cloudflare quick tunnel；后续远端部署阶段已升级为 KV dynamic origin，
  不再在 Worker 源码中写死 quick tunnel URL。
- `_redirects` 保留为静态托管的备用配置；实测 Cloudflare Pages direct upload 下 `/api/health` 未被 `_redirects` 外部 rewrite 命中，因此当前主路径改为 Pages advanced mode Worker proxy。
- 前端生产环境改为同源 `/api/*`，不再依赖绝对 tunnel base URL；本机 `file://` 与 `localhost` 仍自动回落到 `http://127.0.0.1:8001`。
- 本地 `file://`、`localhost`、`127.0.0.1` 访问仍默认请求 `http://127.0.0.1:8001`，保留本地开发体验。
- FastAPI `ENZYME_API_CORS_ORIGINS` 必须包含 `null` 与 `https://shengji-enzyme-rag-lab.pages.dev`，否则 `file://` 调试入口会被浏览器 CORS preflight 拦截。
- Pages `_worker.js` 对 `/api/*` 与 `/PDF/*` 直接处理 `OPTIONS`，并为 proxy response 添加 CORS headers，避免预检请求穿透到后端导致 400。
- Cloudflare Pages 直接上传 `web/`，只包含前端静态文件，不再需要整仓上传。

## 风险

- 当前后端公网入口是 Cloudflare quick tunnel，不是 named tunnel；机器重启、
  LaunchAgent/Compose 重启或 tunnel 重新分配后，trycloudflare URL 可能
  变化。远端部署阶段应通过 Cloudflare KV dynamic origin + sentinel
  自动更新，不再通过手工改 Pages Worker。
- Cloudflare 账号当前没有 zones，不能直接绑定固定 `api.<domain>`。
- 本机后端停止、睡眠、断网或 Qdrant/MinerU 依赖异常时，公网前端仍可打开，但 API 会失败。
- 这是 demo/内测架构，不是生产架构；真实生产应迁移后端到云端或配置固定 named tunnel、访问控制、审计和限流。

## TODO

- [x] 安装并运行 `cloudflared`。
- [x] 启动 quick tunnel 到 `http://127.0.0.1:8001`。
- [x] 修改前端生产 API base 为同源。
- [x] 添加 Cloudflare Pages `_redirects` 与 `_headers`。
- [x] 添加 Cloudflare Pages `_worker.js` proxy fallback，修复 `/api/*` 返回首页 HTML 的问题。
- [x] 修复本地 `file://` 与 Pages proxy 的 CORS/OPTIONS，避免论文目录和问答请求显示泛化 `请求失败 Error`。
- [x] 创建 Cloudflare Pages project 并完成生产部署。
- [x] 验证 Cloudflare Pages 页面、同源 `/api/health`、`/api/dashboard/summary`、`/api/documents`。
- [x] 验证 Cloudflare Pages Worker proxy 对 NDJSON stream 的行为，确认 `event: final` 可收到。
- [ ] 接入 Cloudflare zone 后升级为 named tunnel 固定 API 域名。

## 验证标准

- `https://shengji-enzyme-rag-lab.pages.dev/` 返回 200，`index.html` 引用 `260603-cloudflare-pages-cors-v2`。
- `https://shengji-enzyme-rag-lab.pages.dev/api/health` 返回 `status: ok`。
- `https://shengji-enzyme-rag-lab.pages.dev/api/documents` 返回论文目录，包含 `B10`。
- `https://shengji-enzyme-rag-lab.pages.dev/api/dashboard/summary` 返回 Qdrant 和文献统计。
- 以 Pages Origin 直连 Cloudflare stream endpoint，`/api/recommend/by-enzyme/stream` 返回 `event: final`。
- 本地 `http://127.0.0.1:5173/` 论文问答模式显示 `97 篇可选论文`，搜索 `B10` 首项为 `B10.pdf`。
