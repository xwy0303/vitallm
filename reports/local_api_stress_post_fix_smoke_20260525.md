# Local API Stress Test

- Started: `2026-05-25T02:06:44.019101+00:00`
- Finished: `2026-05-25T02:06:47.108821+00:00`
- API: `http://127.0.0.1:8001`
- Web: `http://127.0.0.1:5173`
- Collection: `enzyme_immobilization_b10`
- Stream TTFT definition: elapsed time from request start to first visible `delta` or `first_delta` status.
- Stream suites intentionally use low concurrency because they call the paid remote LLM provider.

## Suite Summary

| Suite | Kind | OK | Failed | Concurrency | RPS | Latency ms |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| api_health | json | 5/5 | 0 | 2 | 393.7 | p50 2.8 / p95 7.0 / max 7.5 |
| api_dashboard_summary | json | 1/1 | 0 | 1 | 0.41 | p50 2427.8 / p95 2427.8 / max 2427.8 |
| api_ingestion_summary | json | 20/20 | 0 | 5 | 53.6 | p50 80.7 / p95 127.2 / max 142.7 |
| web_static | json | 2/2 | 0 | 1 | 158.73 | p50 6.1 / p95 6.4 / max 6.4 |
| web_app_js | json | 20/20 | 0 | 5 | 349.65 | p50 11.8 / p95 19.9 / max 24.0 |
| search_evidence | json | 2/2 | 0 | 1 | 11.24 | p50 88.8 / p95 137.3 / max 142.7 |

## Stream Timings

| Suite | OK | Retrieval ms | Generation start ms | Reasoning ms | First delta ms | Final ms | Output |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| - | - | - | - | - | - | - | - |

## Error Breakdown

- 无。
