from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Optional
import os

import httpx

from enzyme_recommender.runtime.config import RuntimeConfig


PROJECT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_RUNTIME_MIRROR = Path.home() / "Library" / "Application Support" / "Shengji" / "app"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify local LaunchAgent runtime mirror, API collection, Qdrant summary, and optional benchmark."
    )
    parser.add_argument("--workspace", default=PROJECT_DIR, type=Path)
    parser.add_argument("--runtime-mirror", default=DEFAULT_RUNTIME_MIRROR, type=Path)
    parser.add_argument("--config", default=Path("configs/local.yaml"), type=Path)
    parser.add_argument("--api-url", default="http://127.0.0.1:8001")
    parser.add_argument("--run-benchmark", action="store_true")
    parser.add_argument("--benchmark", default=Path("benchmarks/retrieval_smoke.json"), type=Path)
    parser.add_argument("--top-k", default=None, type=int)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    workspace = args.workspace.expanduser().resolve()
    runtime_mirror = args.runtime_mirror.expanduser().resolve()
    config_rel = args.config
    workspace_config_path = resolve_relative_path(workspace, config_rel)
    runtime_config_path = resolve_relative_path(runtime_mirror, config_rel)

    report: Dict[str, Any] = {
        "workspace": str(workspace),
        "runtime_mirror": str(runtime_mirror),
        "checks": {},
        "ok": True,
    }
    workspace_config = load_config(workspace_config_path, report, "workspace_config")
    runtime_config = load_config(runtime_config_path, report, "runtime_config")
    expected_collection = runtime_config.vector_store.collection if runtime_config else None
    if workspace_config and runtime_config:
        set_check(
            report,
            "config_collection_match",
            workspace_config.vector_store.collection == runtime_config.vector_store.collection,
            {
                "workspace_collection": workspace_config.vector_store.collection,
                "runtime_collection": runtime_config.vector_store.collection,
            },
        )

    health = get_json(f"{args.api_url.rstrip('/')}/api/health")
    set_check(report, "api_health", health is not None and health.get("status") == "ok", health or {})
    if health and expected_collection:
        set_check(
            report,
            "api_collection_match",
            health.get("collection") == expected_collection,
            {"api_collection": health.get("collection"), "expected_collection": expected_collection},
        )

    dashboard = get_json(f"{args.api_url.rstrip('/')}/api/dashboard/summary")
    set_check(
        report,
        "dashboard_qdrant_green",
        dashboard is not None and dashboard.get("qdrant_status") == "green",
        dashboard or {},
    )
    if dashboard and expected_collection:
        set_check(
            report,
            "dashboard_collection_match",
            dashboard.get("collection") == expected_collection,
            {"dashboard_collection": dashboard.get("collection"), "expected_collection": expected_collection},
        )

    if args.run_benchmark:
        benchmark = run_benchmark(workspace, config_rel, args.benchmark, args.top_k)
        set_check(
            report,
            "retrieval_benchmark",
            benchmark.get("returncode") == 0,
            benchmark,
        )

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print_human_report(report)
    if not report["ok"]:
        raise SystemExit(2)


def resolve_relative_path(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def load_config(path: Path, report: Dict[str, Any], check_name: str) -> Optional[RuntimeConfig]:
    try:
        config = RuntimeConfig.from_file(path)
    except Exception as exc:
        set_check(report, check_name, False, {"path": str(path), "error": str(exc)})
        return None
    set_check(report, check_name, True, {"path": str(path), "collection": config.vector_store.collection})
    return config


def get_json(url: str) -> Optional[Dict[str, Any]]:
    try:
        response = httpx.get(url, timeout=15.0, trust_env=False)
        response.raise_for_status()
        payload = response.json()
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def run_benchmark(workspace: Path, config_path: Path, benchmark_path: Path, top_k: Optional[int]) -> Dict[str, Any]:
    cmd = [
        str(workspace / ".venv" / "bin" / "python"),
        str(workspace / "scripts" / "benchmark_retrieval.py"),
        "--config",
        str(resolve_relative_path(workspace, config_path)),
        "--benchmark",
        str(resolve_relative_path(workspace, benchmark_path)),
        "--json",
    ]
    if top_k is not None:
        cmd.extend(["--top-k", str(top_k)])
    env = os.environ.copy()
    env["PYTHONPATH"] = str(workspace / "src")
    completed = subprocess.run(
        cmd,
        cwd=workspace,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    parsed: Any = None
    if completed.stdout.strip():
        try:
            parsed = json.loads(completed.stdout)
        except json.JSONDecodeError:
            parsed = completed.stdout[-2000:]
    return {
        "returncode": completed.returncode,
        "stdout": parsed,
        "stderr_tail": completed.stderr[-2000:],
    }


def set_check(report: Dict[str, Any], name: str, ok: bool, details: Dict[str, Any]) -> None:
    report["checks"][name] = {"ok": ok, **details}
    report["ok"] = bool(report["ok"] and ok)


def print_human_report(report: Dict[str, Any]) -> None:
    print(f"Workspace: {report['workspace']}")
    print(f"Runtime mirror: {report['runtime_mirror']}")
    for name, check in report["checks"].items():
        status = "OK" if check.get("ok") else "FAIL"
        print(f"{status} {name}")
        details = {key: value for key, value in check.items() if key != "ok"}
        if details:
            print(json.dumps(details, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
