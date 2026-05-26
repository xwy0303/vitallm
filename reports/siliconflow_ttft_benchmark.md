# SiliconFlow TTFT Benchmark

- Started: `2026-05-24T15:45:53.486582+00:00`
- Finished: `2026-05-24T15:55:15.926505+00:00`
- Base URL: `https://api.siliconflow.cn/v1`
- Trials per model: `3`
- Timeout: `180.0s`
- Temperature: `0.1`
- Max tokens: `220`
- TTFT definition: elapsed time from request start to first non-empty streaming `delta.content`.

## Summary

| Model | Success | TTFT ms | First SSE event ms | Total ms | Output | Errors |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Qwen/Qwen3.6-27B | 0/3 | - | - | - | - | trial 1: stream ended without non-empty delta.content<br>trial 2: stream ended without non-empty delta.content<br>trial 3: stream ended without non-empty delta.content |
| Qwen/Qwen3.6-35B-A3B | 0/3 | - | - | - | - | trial 1: stream ended without non-empty delta.content<br>trial 2: stream ended without non-empty delta.content<br>trial 3: ReadTimeout: The read operation timed out |
| deepseek-ai/DeepSeek-V4-Flash | 3/3 | median 679.8 / min 646.1 / max 687.7 | median 679.7 / min 646.1 / max 687.7 | median 23960.7 / min 21771.8 / max 26763.6 | median 523.0 chars / min 478.0 / max 637.0 | - |
| Pro/zai-org/GLM-5.1 | 3/3 | median 20901.9 / min 20462.9 / max 21508.8 | median 639.0 / min 622.2 / max 726.5 | median 24778.9 / min 23401.0 / max 25444.7 | median 777.0 chars / min 645.0 / max 820.0 | - |
| Pro/moonshotai/Kimi-K2.6 | 3/3 | median 47902.4 / min 43637.4 / max 51148.2 | median 618.3 / min 354.7 / max 1306.0 | median 51259.8 / min 46731.4 / max 54048.6 | median 865.0 chars / min 809.0 / max 874.0 | - |

## TTFT Ranking

1. `deepseek-ai/DeepSeek-V4-Flash` - median TTFT 679.8 ms
2. `Pro/zai-org/GLM-5.1` - median TTFT 20901.9 ms
3. `Pro/moonshotai/Kimi-K2.6` - median TTFT 47902.4 ms

## Prompt

```json
[
  {
    "role": "system",
    "content": "You are an evidence-first enzyme immobilization assistant. Answer as a compact JSON object with fields recommendation, rationale, risks."
  },
  {
    "role": "user",
    "content": "For Burkholderia cepacia lipase used in soybean oil ethanolysis for biodiesel, recommend one immobilization carrier and key conditions. Keep the answer concise."
  }
]
```
