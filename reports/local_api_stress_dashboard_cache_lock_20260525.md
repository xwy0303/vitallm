# Local API Stress Test

- Started: `2026-05-25T02:18:10.166268+00:00`
- Finished: `2026-05-25T02:18:15.897613+00:00`
- API: `http://127.0.0.1:8001`
- Web: `http://127.0.0.1:5173`
- Collection: `enzyme_immobilization_b10`
- Stream TTFT definition: elapsed time from request start to first visible `delta` or `first_delta` status.
- Stream suites intentionally use low concurrency because they call the paid remote LLM provider.

## Suite Summary

| Suite | Kind | OK | Failed | Concurrency | RPS | Latency ms |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| api_health | json | 50/50 | 0 | 10 | 610.5 | p50 14.3 / p95 24.8 / max 30.4 |
| api_dashboard_summary | json | 100/100 | 0 | 20 | 35.43 | p50 60.8 / p95 2559.5 / max 2565.4 |
| api_ingestion_summary | json | 50/50 | 0 | 10 | 54.17 | p50 177.2 / p95 273.5 / max 292.2 |
| web_static | json | 20/20 | 0 | 5 | 273.97 | p50 14.3 / p95 22.9 / max 23.7 |
| web_app_js | json | 20/20 | 0 | 5 | 472.81 | p50 9.3 / p95 13.0 / max 13.2 |
| search_evidence | json | 10/10 | 0 | 2 | 5.68 | p50 247.4 / p95 723.7 / max 759.8 |

## Stream Timings

| Suite | OK | Retrieval ms | Generation start ms | Reasoning ms | First delta ms | Final ms | Output |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| - | - | - | - | - | - | - | - |

## Error Breakdown

- 无。
