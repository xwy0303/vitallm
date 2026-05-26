# Local API Stress Test

- Started: `2026-05-25T02:13:11.976629+00:00`
- Finished: `2026-05-25T02:15:39.533725+00:00`
- API: `http://127.0.0.1:8001`
- Web: `http://127.0.0.1:5173`
- Collection: `enzyme_immobilization_b10`
- Stream TTFT definition: elapsed time from request start to first visible `delta` or `first_delta` status.
- Stream suites intentionally use low concurrency because they call the paid remote LLM provider.

## Suite Summary

| Suite | Kind | OK | Failed | Concurrency | RPS | Latency ms |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| api_health | json | 400/400 | 0 | 80 | 356.89 | p50 111.0 / p95 549.6 / max 954.4 |
| api_dashboard_summary | json | 40/100 | 60 | 20 | 1.08 | p50 30005.5 / p95 30044.0 / max 30054.9 |
| api_ingestion_summary | json | 50/50 | 0 | 10 | 20.0 | p50 390.4 / p95 726.6 / max 821.9 |
| web_static | json | 299/300 | 1 | 60 | 59.49 | p50 18.7 / p95 1139.6 / max 5014.6 |
| web_app_js | json | 150/150 | 0 | 30 | 812.13 | p50 15.3 / p95 144.9 / max 173.4 |
| search_evidence | json | 120/120 | 0 | 20 | 2.61 | p50 6884.1 / p95 12821.2 / max 16153.3 |

## Stream Timings

| Suite | OK | Retrieval ms | Generation start ms | Reasoning ms | First delta ms | Final ms | Output |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| - | - | - | - | - | - | - | - |

## Error Breakdown

- `api_dashboard_summary` x60: ReadTimeout:
- `web_static` x1: ConnectTimeout:
