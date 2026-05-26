# Local API Stress Test

- Started: `2026-05-25T01:58:10.688181+00:00`
- Finished: `2026-05-25T02:01:08.542312+00:00`
- API: `http://127.0.0.1:8001`
- Web: `http://127.0.0.1:5173`
- Collection: `enzyme_immobilization_b10`
- Stream TTFT definition: elapsed time from request start to first visible `delta` or `first_delta` status.
- Stream suites intentionally use low concurrency because they call the paid remote LLM provider.

## Suite Summary

| Suite | Kind | OK | Failed | Concurrency | RPS | Latency ms |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| api_health | json | 20/20 | 0 | 5 | 584.8 | p50 5.4 / p95 15.0 / max 15.2 |
| api_dashboard_summary | json | 5/5 | 0 | 1 | 0.42 | p50 2384.0 / p95 2440.6 / max 2443.6 |
| api_ingestion_summary | json | 20/20 | 0 | 5 | 55.16 | p50 87.8 / p95 104.4 / max 107.4 |
| web_static | json | 10/10 | 0 | 2 | 222.72 | p50 7.2 / p95 11.7 / max 12.4 |
| web_app_js | json | 20/20 | 0 | 5 | 358.42 | p50 12.4 / p95 17.0 / max 19.1 |
| search_evidence | json | 10/10 | 0 | 2 | 5.82 | p50 294.2 / p95 701.6 / max 715.9 |
| stream_recommendation | stream | 2/3 | 1 | 1 | 0.03 | p50 40947.3 / p95 45229.5 / max 45705.3 |
| stream_formulation | stream | 2/2 | 0 | 1 | 0.03 | p50 32273.5 / p95 54925.6 / max 57442.5 |

## Stream Timings

| Suite | OK | Retrieval ms | Generation start ms | Reasoning ms | First delta ms | Final ms | Output |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| stream_recommendation | 2/3 | p50 39.2 / p95 39.6 / max 39.6 | p50 44.9 / p95 48.4 / max 48.8 | - | p50 1151.5 / p95 3554.2 / max 3821.2 | p50 26680.6 / p95 39515.9 / max 40942.0 | p50 675.0 chars / p95 823.5 / max 840.0 |
| stream_formulation | 2/2 | p50 44.1 / p95 45.6 / max 45.8 | p50 55.2 / p95 56.1 / max 56.2 | - | p50 777.6 / p95 950.0 / max 969.1 | p50 32260.0 / p95 54914.7 / max 57431.9 | p50 1452.0 chars / p95 1565.4 / max 1578.0 |

## Error Breakdown

- `stream_recommendation` x1: stream generation failed for provider siliconflow: provider siliconflow did not return data before read timeout (The read operation timed out)
