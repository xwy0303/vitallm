# 本地 API 压测汇总 2026-05-25

## 结论

本次压测确认：前端卡在“模型建议生成中”不是检索慢，也不是基础 API/Web 服务慢。推荐链路在后端约 40-55 ms 内完成 retrieval 和 evidence preview，随后进入 SiliconFlow stream。成功样本的首个可见 token 在 0.6-3.8 s 内返回；慢的是模型完整输出，总耗时可到 40-57 s，并且出现过一次 provider stream read timeout。

本地服务另有一个独立瓶颈：`/api/dashboard/summary` 每次实时扫描 PDF/artifacts/Qdrant，在高并发下会造成 API 排队和 30 s timeout。该瓶颈会影响首页指标刷新，不是推荐首 token 慢的直接原因。

## 压测报告

- 非 LLM 高并发报告：`reports/local_api_stress_non_llm_20260525_0950.md`
- 真实 LLM stream 报告：`reports/local_api_stress_stream_20260525_0958.md`
- 压测脚本：`scripts/stress_local_api.py`

## 关键数据

| 路径 | 压测配置 | 成功率 | 关键延迟 |
| --- | ---: | ---: | --- |
| `/api/health` | 400 requests / 80 concurrency | 400/400 | p50 78.7 ms, p95 111.8 ms |
| Web `/` | 300 requests / 60 concurrency | 300/300 | p50 44.7 ms, p95 210.6 ms |
| Web `/app.js` | 150 requests / 30 concurrency | 150/150 | p50 12.2 ms, p95 249.9 ms |
| `/api/search/evidence` | 120 requests / 20 concurrency | 120/120 | p50 6761.1 ms, p95 13714.8 ms |
| `/api/dashboard/summary` | 100 requests / 20 concurrency | 1/100 | 99 次 ReadTimeout，p50 30011.7 ms |
| `/api/ingestion/summary` | 50 requests / 10 concurrency | 40/50 | 受 dashboard 队列影响，10 次 ReadTimeout |
| recommend stream | 3 requests / 1 concurrency | 2/3 | first delta p50 1151.5 ms, final p50 26680.6 ms |
| formulation stream | 2 requests / 1 concurrency | 2/2 | first delta p50 777.6 ms, final p50 32260.0 ms |

## Stream 诊断

`recommend/by-enzyme/stream` 单次明细：

| Trial | 结果 | retrieval | generation_start | first_delta | first_delta - generation_start | final | 输出 |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | OK | 39.2 ms | 44.9 ms | 3821.2 ms | 3776.3 ms | 40942.0 ms | 840 chars |
| 2 | OK | 37.5 ms | 41.1 ms | 1151.5 ms | 1110.4 ms | 12419.2 ms | 675 chars |
| 3 | Failed | 39.6 ms | 48.8 ms | 688.0 ms | 639.2 ms | - | 2 chars |

失败原因：

```text
stream generation failed for provider siliconflow: provider siliconflow did not return data before read timeout (The read operation timed out)
```

这说明当前主要风险是 provider stream 中途停顿，而不是后端没有开始生成。前端的 45 s first-token watchdog 能覆盖“完全没有首 token”的情况，但对“吐出极少 token 后长时间不动”的情况还需要增加 stream idle watchdog。

## 已修正

- 新增本地压测脚本，覆盖 API health、dashboard、ingestion summary、Web static、evidence search、recommend stream、formulation stream。
- LaunchAgents runtime 已重新同步并重启。
- 修复 `ingestion-worker` wrapper 在 macOS bash 3.2 + `set -u` 下空数组展开导致反复退出的问题；当前 worker 进程已能正常启动。
- Web 静态服务已使用 `Cache-Control: no-store`，避免前端 JS 缓存导致“修了但没生效”。
- 给 `/api/dashboard/summary` 增加按 collection 维度的 60 s TTL cache 和 in-flight lock，防止高并发冷缓存击穿。
- 给前端 NDJSON stream 增加 45 s idle watchdog，覆盖“已收到少量 token 后上游 stream 长时间静默”的卡住场景。

## 修复后复测

报告：`reports/local_api_stress_dashboard_cache_lock_20260525.md`

| 路径 | 压测配置 | 修复前 | 修复后 |
| --- | ---: | --- | --- |
| `/api/dashboard/summary` | 100 requests / 20 concurrency | 1/100 OK，99 次 ReadTimeout，p95 30052.5 ms | 100/100 OK，p95 2559.5 ms |
| `/api/ingestion/summary` | 50 requests / 10 concurrency | 40/50 OK，受 dashboard 队列影响 10 次 ReadTimeout | 50/50 OK，p95 273.5 ms |
| `/api/search/evidence` | 10 requests / 2 concurrency | 低并发 p95 701.6 ms | 10/10 OK，p95 723.7 ms |

## 优化建议

1. 中期做：search/retrieval 并发优化。低并发 p95 约 702 ms，高并发 p95 约 13.7 s，说明 Qdrant 查询或 Python sync route/threadpool 在并发下排队明显。
2. 中期做：provider 级降级策略。SiliconFlow stream 读超时后应返回已生成 partial content 或明确错误状态，前端不要停留在“模型建议生成中”。
3. 中期做：dashboard summary 后续可从 60 s cache 演进为后台预聚合，避免每个 API 进程各自维护内存 cache。
