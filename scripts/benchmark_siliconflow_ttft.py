from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import httpx


DEFAULT_MODELS = [
    "Qwen/Qwen3.6-27B",
    "Qwen/Qwen3.6-35B-A3B",
    "deepseek-ai/DeepSeek-V4-Flash",
    "Pro/zai-org/GLM-5.1",
    "Pro/moonshotai/Kimi-K2.6",
]

DEFAULT_MESSAGES = [
    {
        "role": "system",
        "content": (
            "You are an evidence-first enzyme immobilization assistant. "
            "Answer as a compact JSON object with fields recommendation, rationale, risks."
        ),
    },
    {
        "role": "user",
        "content": (
            "For Burkholderia cepacia lipase used in soybean oil ethanolysis for biodiesel, "
            "recommend one immobilization carrier and key conditions. Keep the answer concise."
        ),
    },
]


@dataclass
class TrialResult:
    model: str
    trial: int
    ok: bool
    status_code: int | None = None
    first_event_ms: float | None = None
    first_reasoning_ms: float | None = None
    ttft_ms: float | None = None
    total_ms: float | None = None
    reasoning_chars: int = 0
    output_chars: int = 0
    finish_reason: str | None = None
    error: str | None = None


@dataclass
class ModelSummary:
    model: str
    ok_trials: int
    failed_trials: int
    ttft_ms: dict[str, float | None] = field(default_factory=dict)
    first_event_ms: dict[str, float | None] = field(default_factory=dict)
    first_reasoning_ms: dict[str, float | None] = field(default_factory=dict)
    total_ms: dict[str, float | None] = field(default_factory=dict)
    reasoning_chars: dict[str, float | None] = field(default_factory=dict)
    output_chars: dict[str, float | None] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark SiliconFlow streaming TTFT for OpenAI-compatible chat models.")
    parser.add_argument("--base-url", default="https://api.siliconflow.cn/v1")
    parser.add_argument("--api-key-env", default="SILICONFLOW_API_KEY")
    parser.add_argument("--models", nargs="*", default=DEFAULT_MODELS)
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--temperature", type=float, default=0.1)
    parser.add_argument("--max-tokens", type=int, default=0, help="0 omits max_tokens, matching the application request.")
    parser.add_argument("--thinking-budget", type=int, default=0, help="0 omits thinking_budget, matching the application request.")
    parser.add_argument("--without-json-response", action="store_true")
    parser.add_argument("--sleep", type=float, default=1.5, help="Seconds to sleep between trials.")
    parser.add_argument("--output", type=Path, default=Path("reports/siliconflow_ttft_benchmark.json"))
    parser.add_argument("--markdown", type=Path, default=Path("reports/siliconflow_ttft_benchmark.md"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    load_local_env_files()
    api_key = os.environ.get(args.api_key_env)
    if not api_key:
        print(f"Missing API key env var: {args.api_key_env}", file=sys.stderr)
        return 2

    started_at = datetime.now(timezone.utc).isoformat()
    all_results: list[TrialResult] = []
    for model in args.models:
        for trial in range(1, args.trials + 1):
            result = run_trial(
                base_url=args.base_url,
                api_key=api_key,
                model=model,
                trial=trial,
                timeout=args.timeout,
                temperature=args.temperature,
                max_tokens=args.max_tokens,
                thinking_budget=args.thinking_budget,
                json_response=not args.without_json_response,
            )
            all_results.append(result)
            print(format_trial_line(result), flush=True)
            if args.sleep > 0 and not (model == args.models[-1] and trial == args.trials):
                time.sleep(args.sleep)

    payload = {
        "started_at": started_at,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "base_url": args.base_url,
        "api_key_env": args.api_key_env,
        "trials_per_model": args.trials,
        "timeout_seconds": args.timeout,
        "temperature": args.temperature,
        "max_tokens": args.max_tokens,
        "thinking_budget": args.thinking_budget,
        "json_response": not args.without_json_response,
        "messages": DEFAULT_MESSAGES,
        "results": [result.__dict__ for result in all_results],
        "summaries": [summary.__dict__ for summary in summarize_results(all_results)],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    args.markdown.write_text(render_markdown_report(payload), encoding="utf-8")
    print(f"Wrote {args.output}")
    print(f"Wrote {args.markdown}")
    return 0


def run_trial(
    *,
    base_url: str,
    api_key: str,
    model: str,
    trial: int,
    timeout: float,
    temperature: float,
    max_tokens: int,
    thinking_budget: int,
    json_response: bool,
) -> TrialResult:
    payload = {
        "model": model,
        "messages": DEFAULT_MESSAGES,
        "temperature": temperature,
        "stream": True,
    }
    if max_tokens > 0:
        payload["max_tokens"] = max_tokens
    if thinking_budget > 0:
        payload["thinking_budget"] = thinking_budget
    if json_response:
        payload["response_format"] = {"type": "json_object"}
    start = time.perf_counter()
    first_event_ms: float | None = None
    first_reasoning_ms: float | None = None
    ttft_ms: float | None = None
    reasoning_chars = 0
    output_chars = 0
    finish_reason: str | None = None
    status_code: int | None = None

    try:
        with httpx.Client(timeout=httpx.Timeout(timeout), trust_env=False) as client:
            with client.stream(
                "POST",
                f"{base_url.rstrip('/')}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "Accept": "text/event-stream",
                },
                json=payload,
            ) as response:
                status_code = response.status_code
                response.raise_for_status()
                for raw_line in response.iter_lines():
                    now = time.perf_counter()
                    if not raw_line:
                        continue
                    line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else str(raw_line)
                    line = line.strip()
                    if not line or line.startswith(":"):
                        continue
                    if first_event_ms is None:
                        first_event_ms = elapsed_ms(start, now)
                    if line.startswith("data:"):
                        line = line[5:].strip()
                    if line == "[DONE]":
                        break
                    data = json.loads(line)
                    choices = data.get("choices") or []
                    choice = choices[0] if choices else {}
                    delta = choice.get("delta") or {}
                    reasoning_content = str(delta.get("reasoning_content") or "")
                    content = str(delta.get("content") or "")
                    finish_reason = choice.get("finish_reason") or finish_reason
                    if reasoning_content:
                        reasoning_chars += len(reasoning_content)
                        if first_reasoning_ms is None:
                            first_reasoning_ms = elapsed_ms(start, now)
                    if content:
                        output_chars += len(content)
                        if ttft_ms is None:
                            ttft_ms = elapsed_ms(start, now)
                total_ms = elapsed_ms(start, time.perf_counter())
    except Exception as exc:
        return TrialResult(
            model=model,
            trial=trial,
            ok=False,
            status_code=status_code,
            first_event_ms=first_event_ms,
            first_reasoning_ms=first_reasoning_ms,
            total_ms=elapsed_ms(start, time.perf_counter()),
            reasoning_chars=reasoning_chars,
            output_chars=output_chars,
            finish_reason=finish_reason,
            error=safe_error(exc),
        )

    return TrialResult(
        model=model,
        trial=trial,
        ok=ttft_ms is not None,
        status_code=status_code,
        first_event_ms=first_event_ms,
        first_reasoning_ms=first_reasoning_ms,
        ttft_ms=ttft_ms,
        total_ms=total_ms,
        reasoning_chars=reasoning_chars,
        output_chars=output_chars,
        finish_reason=finish_reason,
        error=None if ttft_ms is not None else "stream ended without non-empty delta.content",
    )


def summarize_results(results: Iterable[TrialResult]) -> list[ModelSummary]:
    by_model: dict[str, list[TrialResult]] = {}
    for result in results:
        by_model.setdefault(result.model, []).append(result)

    summaries = []
    for model, model_results in by_model.items():
        ok_results = [result for result in model_results if result.ok]
        summaries.append(
            ModelSummary(
                model=model,
                ok_trials=len(ok_results),
                failed_trials=len(model_results) - len(ok_results),
                ttft_ms=stats([result.ttft_ms for result in ok_results]),
                first_event_ms=stats([result.first_event_ms for result in model_results]),
                first_reasoning_ms=stats([result.first_reasoning_ms for result in model_results]),
                total_ms=stats([result.total_ms for result in model_results]),
                reasoning_chars=stats([float(result.reasoning_chars) for result in model_results]),
                output_chars=stats([float(result.output_chars) for result in ok_results]),
                errors=[f"trial {result.trial}: {result.error}" for result in model_results if result.error],
            )
        )
    return summaries


def stats(values: Iterable[float | None]) -> dict[str, float | None]:
    normalized = [float(value) for value in values if value is not None]
    if not normalized:
        return {"min": None, "median": None, "mean": None, "max": None}
    return {
        "min": round(min(normalized), 1),
        "median": round(statistics.median(normalized), 1),
        "mean": round(statistics.fmean(normalized), 1),
        "max": round(max(normalized), 1),
    }


def elapsed_ms(start: float, end: float) -> float:
    return round((end - start) * 1000, 1)


def safe_error(exc: Exception) -> str:
    text = f"{type(exc).__name__}: {exc}"
    return text.replace(os.environ.get("SILICONFLOW_API_KEY", ""), "[redacted]")


def format_trial_line(result: TrialResult) -> str:
    if result.ok:
        return (
            f"{result.model} trial={result.trial} ok "
            f"first_event={result.first_event_ms}ms first_reasoning={result.first_reasoning_ms}ms "
            f"ttft={result.ttft_ms}ms total={result.total_ms}ms "
            f"reasoning_chars={result.reasoning_chars} content_chars={result.output_chars}"
        )
    return (
        f"{result.model} trial={result.trial} failed first_event={result.first_event_ms}ms "
        f"first_reasoning={result.first_reasoning_ms}ms total={result.total_ms}ms "
        f"reasoning_chars={result.reasoning_chars} error={result.error}"
    )


def render_markdown_report(payload: dict[str, Any]) -> str:
    summaries = payload["summaries"]
    rows = []
    for summary in summaries:
        rows.append(
            "| {model} | {ok}/{total} | {ttft} | {reasoning} | {first_event} | {total_ms} | {chars} | {errors} |".format(
                model=summary["model"],
                ok=summary["ok_trials"],
                total=summary["ok_trials"] + summary["failed_trials"],
                ttft=format_stat(summary["ttft_ms"]),
                reasoning=format_stat(summary["first_reasoning_ms"]),
                first_event=format_stat(summary["first_event_ms"]),
                total_ms=format_stat(summary["total_ms"]),
                chars=format_stat(summary["output_chars"], suffix=" chars"),
                errors="<br>".join(summary["errors"]) if summary["errors"] else "-",
            )
        )

    sorted_ok = sorted(
        [summary for summary in summaries if summary["ttft_ms"]["median"] is not None],
        key=lambda item: item["ttft_ms"]["median"],
    )
    ranking = "\n".join(
        f"{index}. `{summary['model']}` - median TTFT {summary['ttft_ms']['median']} ms"
        for index, summary in enumerate(sorted_ok, start=1)
    )
    if not ranking:
        ranking = "无成功样本。"

    return "\n".join(
        [
            "# SiliconFlow TTFT Benchmark",
            "",
            f"- Started: `{payload['started_at']}`",
            f"- Finished: `{payload['finished_at']}`",
            f"- Base URL: `{payload['base_url']}`",
            f"- Trials per model: `{payload['trials_per_model']}`",
            f"- Timeout: `{payload['timeout_seconds']}s`",
            f"- Temperature: `{payload['temperature']}`",
            f"- Max tokens: `{'omitted (provider default)' if payload['max_tokens'] == 0 else payload['max_tokens']}`",
            f"- Thinking budget: `{'omitted (provider default)' if payload['thinking_budget'] == 0 else payload['thinking_budget']}`",
            f"- JSON response format: `{payload['json_response']}`",
            "- Visible TTFT definition: elapsed time from request start to first non-empty streaming `delta.content`.",
            "- Reasoning onset definition: elapsed time to first non-empty `delta.reasoning_content`; it is not displayed by the current UI.",
            "",
            "## Summary",
            "",
            "| Model | Visible content | Visible TTFT ms | Reasoning onset ms | First SSE event ms | Total ms | Output | Errors |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
            *rows,
            "",
            "## TTFT Ranking",
            "",
            ranking,
            "",
            "## Prompt",
            "",
            "```json",
            json.dumps(payload["messages"], ensure_ascii=False, indent=2),
            "```",
            "",
        ]
    )


def format_stat(value: dict[str, float | None], suffix: str = "") -> str:
    if value["median"] is None:
        return "-"
    return f"median {value['median']}{suffix} / min {value['min']} / max {value['max']}"


def load_local_env_files() -> None:
    for path in [Path.cwd() / ".env.local", Path.cwd() / ".env"]:
        if not path.exists():
            continue
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


if __name__ == "__main__":
    raise SystemExit(main())
