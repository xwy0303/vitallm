# Netlify + Cloudflare Quick Tunnel Demo Deploy

## 现状分析

- 前端静态资源位于 `web/`，入口为 `web/index.html`、`web/app.js`、`web/styles.css`。
- 本机 FastAPI 后端运行在 `http://127.0.0.1:8001`，`/api/health` 可用。
- Cloudflare quick tunnel 通过 LaunchAgent `com.shengji.cloudflared.quick` 暴露本机后端。
- Netlify 站点 `shengji-enzyme-rag-lab` 已创建，site id 为 `c2a6143f-51f0-42a1-9e9c-14f5bb265b50`。

## 工程方案

- 前端生产环境默认使用同源 API base：`API_BASE_URL=""`。
- Netlify `netlify.toml` 将 `/api/*` rewrite 到当前 Cloudflare quick tunnel：
  `https://measurements-ban-lesser-sent.trycloudflare.com/api/:splat`。
- Netlify rewrite 会提前结束当前 NDJSON 长流，导致前端报“流式响应结束，但没有收到最终结果”。修复后：
  - 普通 JSON API 继续走 Netlify 同源 `/api/*` rewrite。
  - NDJSON stream endpoint 使用 `window.ENZYME_STREAM_API_BASE_URL` 直连 Cloudflare quick tunnel。
  - 本机 FastAPI CORS 显式允许 `https://shengji-enzyme-rag-lab.netlify.app`。
- 本地 `file://`、`localhost`、`127.0.0.1` 访问仍默认请求 `http://127.0.0.1:8001`，保留本地开发体验。
- Netlify MCP 整仓上传失败，原因是 repo 内存在 >2GiB 文件；实际部署使用 `.deploy/netlify-shengji/` staging 目录，只包含前端静态文件和 staging 专用 `netlify.toml`。

## 风险

- 当前后端公网入口是 Cloudflare quick tunnel，不是 named tunnel；机器重启、LaunchAgent 重启或 tunnel 重新分配后，trycloudflare URL 可能变化。
- Cloudflare 账号当前没有 zones，不能直接绑定固定 `api.<domain>`。
- 本机后端停止、睡眠、断网或 Qdrant/MinerU 依赖异常时，公网前端仍可打开，但 API 会失败。
- 这是 demo/内测架构，不是生产架构；真实生产应迁移后端到云端或配置固定 named tunnel、访问控制、审计和限流。

## TODO

- [x] 安装并运行 `cloudflared`。
- [x] 启动 quick tunnel 到 `http://127.0.0.1:8001`。
- [x] 修改前端生产 API base 为同源。
- [x] 添加 Netlify rewrite 配置。
- [x] 创建 Netlify site 并完成生产部署。
- [x] 验证 Netlify 页面、同源 `/api/health`、`/api/dashboard/summary`。
- [x] 修复 Netlify rewrite 对 NDJSON stream 的提前截断，验证跨域 stream 可收到 `event: final`。
- [ ] 接入 Cloudflare zone 后升级为 named tunnel 固定 API 域名。

## 验证标准

- `https://shengji-enzyme-rag-lab.netlify.app/` 返回 200。
- `https://shengji-enzyme-rag-lab.netlify.app/api/health` 返回 `status: ok`。
- `https://shengji-enzyme-rag-lab.netlify.app/api/dashboard/summary` 返回 Qdrant 和文献统计。
- 以 Origin `https://shengji-enzyme-rag-lab.netlify.app` 直连 Cloudflare stream endpoint，`/api/recommend/by-enzyme/stream` 返回 `event: final`。
