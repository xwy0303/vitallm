from __future__ import annotations

import argparse
import asyncio
import json
import math
import statistics
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Literal

import httpx


DEFAULT_COLLECTION = ""
DEFAULT_SEARCH_QUERIES = [
    "Burkholderia cepacia lipase ZIF-8 soybean oil ethanolysis biodiesel yield reuse",
    "lipase immobilization carrier glutaraldehyde activity recovery stability",
    "MOF immobilized lipase transesterification ethanol soybean oil",
    "enzyme immobilization evidence carrier pore size operational stability",
]
DEFAULT_RECOMMEND_INPUTS = [
    "Burkholderia cepacia lipase，用于大豆油乙醇酯交换制备 biodiesel，推荐固定化载体和关键条件。",
    "lipase immobilization for biodiesel ethanolysis, optimize carrier choice and reuse stability.",
    "Burkholderia cepacia lipase biodiesel synthesis, evidence-backed immobilization strategy.",
]
DEFAULT_FORMULATION_INPUTS = [
    {
        "enzyme_name": "Burkholderia cepacia lipase",
        "user_formulation": {
            "carrier": "ZIF-8",
            "enzyme_loading": {"value": 500, "unit": "mg/g"},
            "buffer": {"pH": 7.0},
            "immobilization_conditions": {"time": {"value": 60, "unit": "min"}},
        },
        "application_context": "大豆油乙醇酯交换制备 biodiesel，关注活性回收、重复使用稳定性和载体选择。",
    },
    {
        "enzyme_name": "Burkholderia cepacia lipase",
        "user_formulation": {
            "carrier": "magnetic nanoparticle",
            "crosslinker": "glutaraldehyde",
            "buffer": {"pH": 7.5},
        },
        "application_context": "固定化 lipase 配方优化，关注操作稳定性和 evidence traceability。",
    },
]


@dataclass
class SuiteSpec:
    name: str
    kind: Literal["json", "stream"]
    method: str
    url: str
    requests: int
    concurrency: int
    payloads: list[dict[str, Any]] = field(default_factory=list)
    headers: dict[str, str] = field(default_factory=dict)
    expected_status: int = 200


@dataclass
class TrialResult:
    suite: str
    kind: str
    request_id: int
    ok: bool
    status_code: int | None
    latency_ms: float | None
    response_bytes: int = 0
    error: str | None = None
    first_event_ms: float | None = None
    retrieval_ms: float | None = None
    preview_ms: float | None = None
    generation_start_ms: float | None = None
    model_reasoning_ms: float | None = None
    first_delta_ms: float | None = None
    final_ms: float | None = None
    hits_count: int | None = None
    output_chars: int = 0
    event_counts: dict[str, int] = field(default_factory=dict)


@dataclass
class SuiteSummary:
    name: str
    kind: str
    requests: int
    concurrency: int
    ok: int
    failed: int
    wall_ms: float
    rps: float
    latency_ms: dict[str, float | None]
    stream_ms: dict[str, dict[str, float | None]] = field(default_factory=dict)
    output_chars: dict[str, float | None] = field(default_factory=dict)
    hits_count: dict[str, float | None] = field(default_factory=dict)
    errors: list[dict[str, Any]] = field(default_factory=list)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Stress test local Shengji API/Web routes, including NDJSON streams.")
    parser.add_argument("--api-base-url", default="http://127.0.0.1:8001")
    parser.add_argument("--web-base-url", default="http://127.0.0.1:5173")
    parser.add_argument("--collection", default=DEFAULT_COLLECTION)
    parser.add_argument("--json-timeout", type=float, default=30.0)
    parser.add_argument("--stream-timeout", type=float, default=240.0)
    parser.add_argument("--stream-read-timeout", type=float, default=60.0)
    parser.add_argument("--health-requests", type=int, default=200)
    parser.add_argument("--health-concurrency", type=int, default=50)
    parser.add_argument("--dashboard-requests", type=int, default=80)
    parser.add_argument("--dashboard-concurrency", type=int, default=20)
    parser.add_argument("--web-requests", type=int, default=120)
    parser.add_argument("--web-concurrency", type=int, default=30)
    parser.add_argument("--search-requests", type=int, default=60)
    parser.add_argument("--search-concurrency", type=int, default=10)
    parser.add_argument("--stream-requests", type=int, default=3)
    parser.add_argument("--stream-concurrency", type=int, default=1)
    parser.add_argument("--skip-stream", action="store_true", help="Skip paid/remote LLM stream suites.")
    parser.add_argument("--skip-formulation-stream", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=Path("reports"))
    parser.add_argument("--label", default="")
    return parser.parse_args()


async def main_async() -> int:
    args = parse_args()
    started_at = datetime.now(timezone.utc)
    label = args.label.strip() or started_at.strftime("local_api_stress_%Y%m%d_%H%M%S")
    output_json = args.output_dir / f"{label}.json"
    output_md = args.output_dir / f"{label}.md"

    specs = build_suite_specs(args)
    print(f"stress target api={args.api_base_url} web={args.web_base_url} suites={len(specs)}", flush=True)
    all_results: list[TrialResult] = []
    suite_runs: list[dict[str, Any]] = []

    async with httpx.AsyncClient(follow_redirects=False, trust_env=False) as client:
        for spec in specs:
            print(
                f"running suite={spec.name} kind={spec.kind} requests={spec.requests} concurrency={spec.concurrency}",
                flush=True,
            )
            wall_start = time.perf_counter()
            results = await run_suite(client, spec, args)
            wall_ms = elapsed_ms(wall_start)
            all_results.extend(results)
            summary = summarize_suite(spec, results, wall_ms)
            suite_runs.append({"spec": asdict(spec), "summary": asdict(summary)})
            print(
                f"done suite={spec.name} ok={summary.ok}/{summary.requests} "
                f"p95={summary.latency_ms['p95']}ms rps={summary.rps}",
                flush=True,
            )

    finished_at = datetime.now(timezone.utc)
    payload = {
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "api_base_url": args.api_base_url,
        "web_base_url": args.web_base_url,
        "collection": args.collection,
        "config": json_safe(vars(args)),
        "suite_runs": suite_runs,
        "results": [asdict(result) for result in all_results],
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    output_md.write_text(render_markdown(payload), encoding="utf-8")
    print(f"wrote {output_json}", flush=True)
    print(f"wrote {output_md}", flush=True)
    non_stream_ok = all(result.ok for result in all_results if not result.suite.startswith("stream_"))
    return 0 if non_stream_ok else 1


def build_suite_specs(args: argparse.Namespace) -> list[SuiteSpec]:
    api_base = args.api_base_url.rstrip("/")
    web_base = args.web_base_url.rstrip("/")
    collection_payload = {"collection": args.collection} if args.collection else {}
    specs = [
        SuiteSpec(
            name="api_health",
            kind="json",
            method="GET",
            url=f"{api_base}/api/health",
            requests=args.health_requests,
            concurrency=args.health_concurrency,
        ),
        SuiteSpec(
            name="api_dashboard_summary",
            kind="json",
            method="GET",
            url=f"{api_base}/api/dashboard/summary",
            requests=args.dashboard_requests,
            concurrency=args.dashboard_concurrency,
        ),
        SuiteSpec(
            name="api_ingestion_summary",
            kind="json",
            method="GET",
            url=f"{api_base}/api/ingestion/summary",
            requests=max(20, args.dashboard_requests // 2),
            concurrency=max(5, args.dashboard_concurrency // 2),
        ),
        SuiteSpec(
            name="web_static",
            kind="json",
            method="GET",
            url=f"{web_base}/",
            requests=args.web_requests,
            concurrency=args.web_concurrency,
        ),
        SuiteSpec(
            name="web_app_js",
            kind="json",
            method="GET",
            url=f"{web_base}/app.js",
            requests=max(20, args.web_requests // 2),
            concurrency=max(5, args.web_concurrency // 2),
        ),
        SuiteSpec(
            name="search_evidence",
            kind="json",
            method="POST",
            url=f"{api_base}/api/search/evidence",
            requests=args.search_requests,
            concurrency=args.search_concurrency,
            payloads=[
                {
                    "query": query,
                    **collection_payload,
                    "top_k": 5,
                    "usable_only": True,
                }
                for query in DEFAULT_SEARCH_QUERIES
            ],
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        ),
    ]
    if not args.skip_stream:
        specs.append(
            SuiteSpec(
                name="stream_recommendation",
                kind="stream",
                method="POST",
                url=f"{api_base}/api/recommend/by-enzyme/stream",
                requests=args.stream_requests,
                concurrency=args.stream_concurrency,
                payloads=[
                    {
                        "enzyme_name": "Burkholderia cepacia lipase",
                        "application_context": value,
                        **collection_payload,
                        "top_k": 3,
                    }
                    for value in DEFAULT_RECOMMEND_INPUTS
                ],
                headers={"Content-Type": "application/json", "Accept": "application/x-ndjson"},
            )
        )
        if not args.skip_formulation_stream:
            specs.append(
                SuiteSpec(
                    name="stream_formulation",
                    kind="stream",
                    method="POST",
                    url=f"{api_base}/api/optimize/formulation/stream",
                    requests=max(1, min(args.stream_requests, 2)),
                    concurrency=args.stream_concurrency,
                    payloads=[
                        {
                            **payload,
                            **collection_payload,
                            "top_k": 3,
                        }
                        for payload in DEFAULT_FORMULATION_INPUTS
                    ],
                    headers={"Content-Type": "application/json", "Accept": "application/x-ndjson"},
                )
            )
    return [spec for spec in specs if spec.requests > 0 and spec.concurrency > 0]


async def run_suite(
    client: httpx.AsyncClient,
    spec: SuiteSpec,
    args: argparse.Namespace,
) -> list[TrialResult]:
    semaphore = asyncio.Semaphore(spec.concurrency)

    async def one(request_id: int) -> TrialResult:
        async with semaphore:
            if spec.kind == "stream":
                return await run_stream_trial(client, spec, request_id, args)
            return await run_json_trial(client, spec, request_id, args)

    return await asyncio.gather(*(one(request_id) for request_id in range(1, spec.requests + 1)))


async def run_json_trial(
    client: httpx.AsyncClient,
    spec: SuiteSpec,
    request_id: int,
    args: argparse.Namespace,
) -> TrialResult:
    started = time.perf_counter()
    payload = select_payload(spec, request_id)
    try:
        response = await client.request(
            spec.method,
            spec.url,
            json=payload if payload else None,
            headers=spec.headers,
            timeout=httpx.Timeout(args.json_timeout, connect=min(5.0, args.json_timeout)),
        )
        content = await response.aread()
        latency_ms = elapsed_ms(started)
        ok = response.status_code == spec.expected_status
        error = None
        if not ok:
            error = extract_error_message(content, response.status_code)
        return TrialResult(
            suite=spec.name,
            kind=spec.kind,
            request_id=request_id,
            ok=ok,
            status_code=response.status_code,
            latency_ms=latency_ms,
            response_bytes=len(content),
            error=error,
        )
    except Exception as exc:
        return TrialResult(
            suite=spec.name,
            kind=spec.kind,
            request_id=request_id,
            ok=False,
            status_code=None,
            latency_ms=elapsed_ms(started),
            error=safe_error(exc),
        )


async def run_stream_trial(
    client: httpx.AsyncClient,
    spec: SuiteSpec,
    request_id: int,
    args: argparse.Namespace,
) -> TrialResult:
    started = time.perf_counter()
    payload = select_payload(spec, request_id)
    event_counts: Counter[str] = Counter()
    status_code: int | None = None
    response_bytes = 0
    first_event_ms: float | None = None
    retrieval_ms: float | None = None
    preview_ms: float | None = None
    generation_start_ms: float | None = None
    model_reasoning_ms: float | None = None
    first_delta_ms: float | None = None
    final_ms: float | None = None
    hits_count: int | None = None
    output_chars = 0
    stream_error: str | None = None

    timeout = httpx.Timeout(
        args.stream_timeout,
        connect=min(10.0, args.stream_timeout),
        read=args.stream_read_timeout,
        write=min(15.0, args.stream_timeout),
        pool=min(15.0, args.stream_timeout),
    )
    try:
        async with client.stream(
            spec.method,
            spec.url,
            json=payload,
            headers=spec.headers,
            timeout=timeout,
        ) as response:
            status_code = response.status_code
            if response.status_code != spec.expected_status:
                body = await response.aread()
                return TrialResult(
                    suite=spec.name,
                    kind=spec.kind,
                    request_id=request_id,
                    ok=False,
                    status_code=status_code,
                    latency_ms=elapsed_ms(started),
                    response_bytes=len(body),
                    error=extract_error_message(body, response.status_code),
                )

            async for line in response.aiter_lines():
                if not line.strip():
                    continue
                now_ms = elapsed_ms(started)
                if first_event_ms is None:
                    first_event_ms = now_ms
                response_bytes += len(line.encode("utf-8"))
                try:
                    event = json.loads(line)
                except json.JSONDecodeError as exc:
                    stream_error = f"invalid NDJSON event: {exc}"
                    break
                event_name = str(event.get("event") or "unknown")
                event_counts[event_name] += 1
                event_elapsed = to_float(event.get("elapsed_ms")) or now_ms

                if event_name == "retrieval":
                    retrieval_ms = event_elapsed
                    hits_count = to_int(event.get("hits_count"))
                elif event_name == "preview":
                    preview_ms = event_elapsed
                elif event_name == "status":
                    stage = event.get("stage")
                    if stage == "generation_start":
                        generation_start_ms = event_elapsed
                    elif stage == "model_reasoning":
                        model_reasoning_ms = event_elapsed
                    elif stage == "first_delta":
                        first_delta_ms = event_elapsed
                elif event_name == "delta":
                    delta = str(event.get("delta") or "")
                    output_chars += len(delta)
                    if first_delta_ms is None and delta:
                        first_delta_ms = now_ms
                elif event_name == "final":
                    final_ms = event_elapsed
                elif event_name == "error":
                    stream_error = str(event.get("message") or "stream error")
                    break
    except Exception as exc:
        return TrialResult(
            suite=spec.name,
            kind=spec.kind,
            request_id=request_id,
            ok=False,
            status_code=status_code,
            latency_ms=elapsed_ms(started),
            response_bytes=response_bytes,
            error=safe_error(exc),
            first_event_ms=first_event_ms,
            retrieval_ms=retrieval_ms,
            preview_ms=preview_ms,
            generation_start_ms=generation_start_ms,
            model_reasoning_ms=model_reasoning_ms,
            first_delta_ms=first_delta_ms,
            final_ms=final_ms,
            hits_count=hits_count,
            output_chars=output_chars,
            event_counts=dict(event_counts),
        )

    ok = stream_error is None and final_ms is not None and output_chars > 0
    if stream_error is None and not ok:
        stream_error = "stream ended without final event or visible delta"
    return TrialResult(
        suite=spec.name,
        kind=spec.kind,
        request_id=request_id,
        ok=ok,
        status_code=status_code,
        latency_ms=elapsed_ms(started),
        response_bytes=response_bytes,
        error=stream_error,
        first_event_ms=first_event_ms,
        retrieval_ms=retrieval_ms,
        preview_ms=preview_ms,
        generation_start_ms=generation_start_ms,
        model_reasoning_ms=model_reasoning_ms,
        first_delta_ms=first_delta_ms,
        final_ms=final_ms,
        hits_count=hits_count,
        output_chars=output_chars,
        event_counts=dict(event_counts),
    )


def select_payload(spec: SuiteSpec, request_id: int) -> dict[str, Any]:
    if not spec.payloads:
        return {}
    return spec.payloads[(request_id - 1) % len(spec.payloads)]


def summarize_suite(spec: SuiteSpec, results: list[TrialResult], wall_ms: float) -> SuiteSummary:
    errors = Counter(normalize_error(result.error) for result in results if result.error)
    return SuiteSummary(
        name=spec.name,
        kind=spec.kind,
        requests=len(results),
        concurrency=spec.concurrency,
        ok=sum(1 for result in results if result.ok),
        failed=sum(1 for result in results if not result.ok),
        wall_ms=round(wall_ms, 1),
        rps=round((len(results) / wall_ms) * 1000, 2) if wall_ms > 0 else 0,
        latency_ms=stats(result.latency_ms for result in results),
        stream_ms={
            "first_event": stats(result.first_event_ms for result in results),
            "retrieval": stats(result.retrieval_ms for result in results),
            "preview": stats(result.preview_ms for result in results),
            "generation_start": stats(result.generation_start_ms for result in results),
            "model_reasoning": stats(result.model_reasoning_ms for result in results),
            "first_delta": stats(result.first_delta_ms for result in results),
            "final": stats(result.final_ms for result in results),
        }
        if spec.kind == "stream"
        else {},
        output_chars=stats(float(result.output_chars) for result in results if result.output_chars)
        if spec.kind == "stream"
        else {},
        hits_count=stats(float(result.hits_count) for result in results if result.hits_count is not None)
        if spec.kind == "stream"
        else {},
        errors=[{"count": count, "error": error} for error, count in errors.most_common(8)],
    )


def render_markdown(payload: dict[str, Any]) -> str:
    suite_rows = []
    stream_rows = []
    error_lines = []
    for run in payload["suite_runs"]:
        summary = run["summary"]
        suite_rows.append(
            "| {name} | {kind} | {ok}/{requests} | {failed} | {concurrency} | {rps} | {latency} |".format(
                name=summary["name"],
                kind=summary["kind"],
                ok=summary["ok"],
                requests=summary["requests"],
                failed=summary["failed"],
                concurrency=summary["concurrency"],
                rps=summary["rps"],
                latency=format_stats(summary["latency_ms"]),
            )
        )
        if summary["kind"] == "stream":
            stream = summary["stream_ms"]
            stream_rows.append(
                "| {name} | {ok}/{requests} | {retrieval} | {generation} | {reasoning} | {first_delta} | {final} | {chars} |".format(
                    name=summary["name"],
                    ok=summary["ok"],
                    requests=summary["requests"],
                    retrieval=format_stats(stream["retrieval"]),
                    generation=format_stats(stream["generation_start"]),
                    reasoning=format_stats(stream["model_reasoning"]),
                    first_delta=format_stats(stream["first_delta"]),
                    final=format_stats(stream["final"]),
                    chars=format_stats(summary["output_chars"], suffix=" chars"),
                )
            )
        for error in summary["errors"]:
            error_lines.append(f"- `{summary['name']}` x{error['count']}: {error['error']}")

    if not stream_rows:
        stream_rows.append("| - | - | - | - | - | - | - | - |")
    if not error_lines:
        error_lines.append("- 无。")

    return "\n".join(
        [
            "# Local API Stress Test",
            "",
            f"- Started: `{payload['started_at']}`",
            f"- Finished: `{payload['finished_at']}`",
            f"- API: `{payload['api_base_url']}`",
            f"- Web: `{payload['web_base_url']}`",
            f"- Collection override: `{payload['collection'] or 'runtime default'}`",
            "- Stream TTFT definition: elapsed time from request start to first visible `delta` or `first_delta` status.",
            "- Stream suites intentionally use low concurrency because they call the paid remote LLM provider.",
            "",
            "## Suite Summary",
            "",
            "| Suite | Kind | OK | Failed | Concurrency | RPS | Latency ms |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
            *suite_rows,
            "",
            "## Stream Timings",
            "",
            "| Suite | OK | Retrieval ms | Generation start ms | Reasoning ms | First delta ms | Final ms | Output |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
            *stream_rows,
            "",
            "## Error Breakdown",
            "",
            *error_lines,
            "",
        ]
    )


def stats(values: Iterable[float | None]) -> dict[str, float | None]:
    normalized = sorted(float(value) for value in values if value is not None)
    if not normalized:
        return {"min": None, "p50": None, "p95": None, "p99": None, "max": None, "mean": None}
    return {
        "min": round(normalized[0], 1),
        "p50": round(percentile(normalized, 50), 1),
        "p95": round(percentile(normalized, 95), 1),
        "p99": round(percentile(normalized, 99), 1),
        "max": round(normalized[-1], 1),
        "mean": round(statistics.fmean(normalized), 1),
    }


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return math.nan
    if len(values) == 1:
        return values[0]
    rank = (len(values) - 1) * pct / 100
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return values[int(rank)]
    fraction = rank - lower
    return values[lower] * (1 - fraction) + values[upper] * fraction


def format_stats(value: dict[str, float | None], suffix: str = "") -> str:
    if not value or value.get("p50") is None:
        return "-"
    return f"p50 {value['p50']}{suffix} / p95 {value['p95']} / max {value['max']}"


def elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 1)


def extract_error_message(content: bytes, status_code: int) -> str:
    text = content.decode("utf-8", errors="replace").strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return f"HTTP {status_code}: {text[:300]}"
    message = (
        payload.get("error", {}).get("message")
        or payload.get("detail", {}).get("error", {}).get("message")
        or payload.get("detail")
        or payload
    )
    return f"HTTP {status_code}: {short_text(message)}"


def normalize_error(value: str | None) -> str:
    if not value:
        return ""
    return short_text(value, limit=240)


def short_text(value: Any, limit: int = 500) -> str:
    text = " ".join(str(value).split())
    return text if len(text) <= limit else f"{text[:limit].rstrip()}..."


def safe_error(exc: Exception) -> str:
    return short_text(f"{exc.__class__.__name__}: {exc}", limit=500)


def to_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def to_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def json_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    return value


def main() -> int:
    return asyncio.run(main_async())


if __name__ == "__main__":
    raise SystemExit(main())
