# SiliconFlow TTFT Benchmark

- Started: `2026-05-24T15:58:24.171655+00:00`
- Finished: `2026-05-24T16:07:14.715771+00:00`
- Base URL: `https://api.siliconflow.cn/v1`
- Trials per model: `2`
- Timeout: `300.0s`
- Temperature: `0.1`
- Max tokens: `omitted (provider default)`
- Thinking budget: `omitted (provider default)`
- JSON response format: `True`
- Visible TTFT definition: elapsed time from request start to first non-empty streaming `delta.content`.
- Reasoning onset definition: elapsed time to first non-empty `delta.reasoning_content`; it is not displayed by the current UI.

## Summary

| Model | Visible content | Visible TTFT ms | Reasoning onset ms | First SSE event ms | Total ms | Output | Errors |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Qwen/Qwen3.6-27B | 2/2 | median 123952.1 / min 32516.9 / max 215387.2 | median 10267.2 / min 448.5 / max 20086.0 | median 10266.9 / min 448.1 / max 20085.8 | median 134948.1 / min 36328.1 / max 233568.1 | median 658.5 chars / min 629.0 / max 688.0 | - |
| Qwen/Qwen3.6-35B-A3B | 2/2 | median 13400.0 / min 11762.3 / max 15037.7 | median 350.6 / min 298.6 / max 402.5 | median 350.5 / min 298.6 / max 402.4 | median 16211.8 / min 14822.2 / max 17601.3 | median 763.0 chars / min 760.0 / max 766.0 | - |
| deepseek-ai/DeepSeek-V4-Flash | 2/2 | median 459.3 / min 356.8 / max 561.8 | - | median 459.2 / min 356.8 / max 561.7 | median 16227.7 / min 4335.4 / max 28120.0 | median 525.5 chars / min 523.0 / max 528.0 | - |
| Pro/zai-org/GLM-5.1 | 2/2 | median 20479.8 / min 19940.3 / max 21019.2 | median 940.5 / min 841.4 / max 1039.5 | median 940.4 / min 841.3 / max 1039.4 | median 24031.7 / min 23766.7 / max 24296.7 | median 785.5 chars / min 692.0 / max 879.0 | - |
| Pro/moonshotai/Kimi-K2.6 | 2/2 | median 63587.3 / min 43437.8 / max 83736.9 | median 3121.5 / min 574.6 / max 5668.3 | median 3121.3 / min 574.5 / max 5668.2 | median 67081.0 / min 46396.1 / max 87765.9 | median 779.0 chars / min 706.0 / max 852.0 | - |

## TTFT Ranking

1. `deepseek-ai/DeepSeek-V4-Flash` - median TTFT 459.3 ms
2. `Qwen/Qwen3.6-35B-A3B` - median TTFT 13400.0 ms
3. `Pro/zai-org/GLM-5.1` - median TTFT 20479.8 ms
4. `Pro/moonshotai/Kimi-K2.6` - median TTFT 63587.3 ms
5. `Qwen/Qwen3.6-27B` - median TTFT 123952.1 ms

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
