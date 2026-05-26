# Local API Stress Test

- Started: `2026-05-25T01:52:57.170427+00:00`
- Finished: `2026-05-25T01:53:02.656828+00:00`
- API: `http://127.0.0.1:8001`
- Web: `http://127.0.0.1:5173`
- Collection: `enzyme_immobilization_b10`
- Stream TTFT definition: elapsed time from request start to first visible `delta` or `first_delta` status.
- Stream suites intentionally use low concurrency because they call the paid remote LLM provider.

## Suite Summary

| Suite | Kind | OK | Failed | Concurrency | RPS | Latency ms |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| api_health | json | 3/3 | 0 | 1 | 241.94 | p50 2.3 / p95 7.2 / max 7.8 |
| api_dashboard_summary | json | 2/2 | 0 | 1 | 0.41 | p50 2414.1 / p95 2445.4 / max 2448.9 |
| api_ingestion_summary | json | 20/20 | 0 | 5 | 57.09 | p50 84.8 / p95 101.2 / max 142.0 |
| web_static | json | 2/2 | 0 | 1 | 175.44 | p50 5.5 / p95 5.8 / max 5.8 |
| web_app_js | json | 20/20 | 0 | 5 | 326.8 | p50 11.1 / p95 22.8 / max 24.5 |
| search_evidence | json | 2/2 | 0 | 1 | 10.5 | p50 95.1 / p95 150.2 / max 156.3 |

## Stream Timings

| Suite | OK | Retrieval ms | Generation start ms | Reasoning ms | First delta ms | Final ms | Output |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| - | - | - | - | - | - | - | - |

## Error Breakdown

- 无。
