# Local API Stress Test

- Started: `2026-05-25T01:53:32.373680+00:00`
- Finished: `2026-05-25T01:57:28.296604+00:00`
- API: `http://127.0.0.1:8001`
- Web: `http://127.0.0.1:5173`
- Collection: `enzyme_immobilization_b10`
- Stream TTFT definition: elapsed time from request start to first visible `delta` or `first_delta` status.
- Stream suites intentionally use low concurrency because they call the paid remote LLM provider.

## Suite Summary

| Suite | Kind | OK | Failed | Concurrency | RPS | Latency ms |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| api_health | json | 400/400 | 0 | 80 | 863.0 | p50 78.7 / p95 111.8 / max 116.9 |
| api_dashboard_summary | json | 1/100 | 99 | 20 | 0.67 | p50 30011.7 / p95 30052.5 / max 30063.1 |
| api_ingestion_summary | json | 40/50 | 10 | 10 | 1.35 | p50 442.8 / p95 30015.2 / max 30015.7 |
| web_static | json | 300/300 | 0 | 60 | 470.96 | p50 44.7 / p95 210.6 / max 623.6 |
| web_app_js | json | 150/150 | 0 | 30 | 475.29 | p50 12.2 / p95 249.9 / max 308.0 |
| search_evidence | json | 120/120 | 0 | 20 | 2.54 | p50 6761.1 / p95 13714.8 / max 15565.9 |

## Stream Timings

| Suite | OK | Retrieval ms | Generation start ms | Reasoning ms | First delta ms | Final ms | Output |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| - | - | - | - | - | - | - | - |

## Error Breakdown

- `api_dashboard_summary` x99: ReadTimeout:
- `api_ingestion_summary` x10: ReadTimeout:
