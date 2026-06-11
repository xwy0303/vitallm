#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import socket
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping
from urllib.parse import quote, urlparse


QUICK_TUNNEL_RE = re.compile(r"https://[-a-z0-9]+\.trycloudflare\.com", re.IGNORECASE)
DEFAULT_ORIGIN_KEY = "current_backend_origin"
DEFAULT_ALLOWED_SUFFIXES = ".trycloudflare.com"


def log(message: str) -> None:
    print(time.strftime("%Y-%m-%dT%H:%M:%S%z"), message, flush=True)


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values


def load_runtime_env(root: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    env.update(parse_env_file(root / "config" / "runtime.env"))
    env.update(parse_env_file(root / "secrets" / "cloudflare.env"))
    return env


def split_csv(value: str | None, fallback: str = "") -> list[str]:
    source = value if value not in (None, "") else fallback
    return [item.strip().lower() for item in source.split(",") if item.strip()]


def host_matches_suffix(hostname: str, suffix: str) -> bool:
    host = hostname.lower()
    normalized = suffix.lower()
    if not host or not normalized:
        return False
    if normalized.startswith("."):
        return host.endswith(normalized) and len(host) > len(normalized)
    return host == normalized or host.endswith(f".{normalized}")


def normalize_backend_origin(raw_origin: str | None, allowed_suffixes: list[str] | None = None) -> str | None:
    origin = (raw_origin or "").strip().rstrip("/")
    if not origin:
        return None
    parsed = urlparse(origin)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        return None
    if parsed.query or parsed.fragment:
        return None
    if parsed.path not in ("", "/"):
        return None
    suffixes = allowed_suffixes or split_csv(DEFAULT_ALLOWED_SUFFIXES)
    if not any(host_matches_suffix(parsed.hostname or "", suffix) for suffix in suffixes):
        return None
    return f"https://{parsed.netloc}"


def extract_latest_quick_tunnel_url(log_text: str) -> str | None:
    matches = QUICK_TUNNEL_RE.findall(log_text or "")
    if not matches:
        return None
    return matches[-1].rstrip("/")


def http_get_text(url: str, token: str | None = None, timeout: float = 10.0) -> tuple[int, str]:
    headers = {"User-Agent": "vitalab-quick-tunnel-sentinel/1.0"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            return response.status, body
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        return error.code, body
    except (urllib.error.URLError, TimeoutError, socket.timeout) as error:
        return 0, str(error)


def http_put_text(url: str, value: str, token: str, timeout: float = 10.0) -> tuple[int, str]:
    data = value.encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "text/plain; charset=utf-8",
            "User-Agent": "vitalab-quick-tunnel-sentinel/1.0",
        },
        method="PUT",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            return response.status, body
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        return error.code, body
    except (urllib.error.URLError, TimeoutError, socket.timeout) as error:
        return 0, str(error)


@dataclass(frozen=True)
class CloudflareKVClient:
    account_id: str
    namespace_id: str
    token: str

    def value_url(self, key: str) -> str:
        encoded_key = quote(key, safe="")
        return (
            "https://api.cloudflare.com/client/v4/accounts/"
            f"{self.account_id}/storage/kv/namespaces/{self.namespace_id}/values/{encoded_key}"
        )

    def get_value(self, key: str, timeout: float = 10.0) -> str | None:
        status, body = http_get_text(self.value_url(key), self.token, timeout)
        if status == 200:
            return body.strip()
        if status == 404:
            return None
        raise RuntimeError(f"Cloudflare KV get failed with HTTP {status}")

    def put_value(self, key: str, value: str, timeout: float = 10.0) -> None:
        status, body = http_put_text(self.value_url(key), value, self.token, timeout)
        if 200 <= status < 300:
            return
        detail = ""
        try:
            parsed = json.loads(body)
            errors = parsed.get("errors") or []
            if errors:
                detail = f": {errors[0].get('message') or errors[0]}"
        except Exception:
            detail = ""
        raise RuntimeError(f"Cloudflare KV put failed with HTTP {status}{detail}")


def build_kv_client(env: Mapping[str, str]) -> CloudflareKVClient:
    missing = [
        name
        for name in ("CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_KV_NAMESPACE_ID", "CLOUDFLARE_API_TOKEN")
        if not env.get(name)
    ]
    if missing:
        raise RuntimeError(f"missing Cloudflare config: {', '.join(missing)}")
    return CloudflareKVClient(
        account_id=env["CLOUDFLARE_ACCOUNT_ID"],
        namespace_id=env["CLOUDFLARE_KV_NAMESPACE_ID"],
        token=env["CLOUDFLARE_API_TOKEN"],
    )


def health_ok(url: str, timeout: float = 10.0) -> bool:
    status, _ = http_get_text(url, timeout=timeout)
    return 200 <= status < 300


def origin_health_ok(origin: str, timeout: float = 10.0) -> bool:
    return health_ok(f"{origin.rstrip('/')}/api/health", timeout)


def compose_base_command(root: Path, env: Mapping[str, str]) -> list[str]:
    try:
        docker_compose = subprocess.run(
            ["docker", "compose", "version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
    except FileNotFoundError:
        docker_compose = subprocess.CompletedProcess(["docker"], returncode=127)
    if docker_compose.returncode == 0:
        base = ["docker", "compose"]
    else:
        base = ["docker-compose"]
    runtime_env = root / "config" / "runtime.env"
    command = [*base, "--env-file", str(runtime_env)]
    for profile in split_csv(env.get("VITALAB_COMPOSE_PROFILES"), "quick-tunnel"):
        command.extend(["--profile", profile])
    command.extend(["-f", str(root / "deploy" / "compose.yaml")])
    return command


def run_compose(root: Path, env: Mapping[str, str], args: list[str]) -> subprocess.CompletedProcess[str]:
    command = compose_base_command(root, env) + args
    return subprocess.run(command, cwd=root / "deploy", text=True, capture_output=True, check=False)


def restart_quick_tunnel(root: Path, env: Mapping[str, str]) -> None:
    result = run_compose(root, env, ["restart", "cloudflared-quick"])
    if result.returncode != 0:
        raise RuntimeError("failed to restart cloudflared-quick")


def read_cloudflared_logs(root: Path, env: Mapping[str, str], tail_count: int = 200) -> str:
    result = run_compose(root, env, ["logs", "--tail", str(tail_count), "cloudflared-quick"])
    if result.returncode != 0:
        raise RuntimeError("failed to read cloudflared-quick logs")
    return result.stdout + result.stderr


def write_state(root: Path, origin: str) -> None:
    state_path = root / "config" / "current_backend_origin"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(f"{origin}\n", encoding="utf-8")


def read_state(root: Path) -> str | None:
    state_path = root / "config" / "current_backend_origin"
    if not state_path.exists():
        return None
    return state_path.read_text(encoding="utf-8").strip() or None


def put_kv_with_retry(client: CloudflareKVClient, key: str, value: str, attempts: int = 5) -> None:
    delay = 1.0
    for attempt in range(1, attempts + 1):
        try:
            client.put_value(key, value)
            return
        except RuntimeError as error:
            if attempt == attempts:
                raise
            log(f"Cloudflare KV write failed, retrying attempt={attempt}: {error}")
            time.sleep(delay)
            delay = min(delay * 2, 16)


def wait_for_pages_health(pages_url: str, timeout_seconds: float, interval_seconds: float) -> bool:
    if not pages_url:
        return False
    deadline = time.monotonic() + timeout_seconds
    health_url = f"{pages_url.rstrip('/')}/api/health"
    while time.monotonic() <= deadline:
        if health_ok(health_url, timeout=10):
            return True
        time.sleep(interval_seconds)
    return False


def run_once(root: Path, env: Mapping[str, str]) -> bool:
    allowed_suffixes = split_csv(env.get("ALLOWED_BACKEND_HOST_SUFFIXES"), DEFAULT_ALLOWED_SUFFIXES)
    origin_key = env.get("CLOUDFLARE_KV_ORIGIN_KEY") or DEFAULT_ORIGIN_KEY
    api_port = env.get("ENZYME_API_PORT") or "18081"
    local_health_url = f"http://127.0.0.1:{api_port}/api/health"
    health_timeout = float(env.get("SENTINEL_HEALTH_TIMEOUT_SECONDS") or "10")

    if not health_ok(local_health_url, timeout=health_timeout):
        log(f"local API unhealthy: {local_health_url}; skip tunnel restart and KV write")
        return False

    client = build_kv_client(env)
    current_origin = None
    try:
        current_origin = normalize_backend_origin(client.get_value(origin_key), allowed_suffixes)
    except RuntimeError as error:
        log(f"Cloudflare KV read failed; falling back to local state: {error}")
        current_origin = normalize_backend_origin(read_state(root), allowed_suffixes)

    if current_origin and origin_health_ok(current_origin, timeout=health_timeout):
        write_state(root, current_origin)
        log(f"current backend origin healthy: {current_origin}")
        return True

    if current_origin:
        log(f"current backend origin unhealthy: {current_origin}; restarting cloudflared-quick")
    else:
        log("current backend origin missing or invalid; restarting cloudflared-quick")

    restart_quick_tunnel(root, env)
    time.sleep(float(env.get("SENTINEL_TUNNEL_RESTART_WAIT_SECONDS") or "8"))

    log_text = read_cloudflared_logs(root, env, int(env.get("SENTINEL_LOG_TAIL") or "200"))
    new_origin = normalize_backend_origin(extract_latest_quick_tunnel_url(log_text), allowed_suffixes)
    if not new_origin:
        log("could not extract a valid quick tunnel URL from cloudflared logs")
        return False
    if not origin_health_ok(new_origin, timeout=health_timeout):
        log(f"new backend origin failed health check: {new_origin}")
        return False

    if new_origin != current_origin:
        put_kv_with_retry(client, origin_key, new_origin)
        log(f"updated Cloudflare KV origin key={origin_key} origin={new_origin}")
    else:
        log(f"new backend origin matches current KV origin: {new_origin}")
    write_state(root, new_origin)

    pages_url = env.get("CLOUDFLARE_PAGES_URL") or "https://shengji-enzyme-rag-lab.pages.dev"
    pages_timeout = float(env.get("SENTINEL_PAGES_HEALTH_TIMEOUT_SECONDS") or "90")
    if wait_for_pages_health(pages_url, pages_timeout, 5):
        log(f"Pages proxy healthy: {pages_url}/api/health")
    else:
        log(f"WARNING: Pages proxy did not become healthy within {pages_timeout:.0f}s")
    return True


def derive_root(script_path: Path) -> Path:
    return script_path.resolve().parents[2]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Monitor quick tunnel origin and publish it to Cloudflare KV.")
    parser.add_argument("--root", type=Path, default=derive_root(Path(__file__)))
    parser.add_argument("--once", action="store_true", help="Run one reconciliation pass.")
    parser.add_argument("--loop", action="store_true", help="Run continuously.")
    parser.add_argument("--print-kv-origin", action="store_true", help="Print current KV origin and exit.")
    parser.add_argument("--extract-latest-origin", type=Path, help="Extract latest quick tunnel URL from a log file.")
    args = parser.parse_args(argv)

    if args.extract_latest_origin:
        print(extract_latest_quick_tunnel_url(args.extract_latest_origin.read_text(encoding="utf-8")) or "")
        return 0

    root = args.root.resolve()
    env = load_runtime_env(root)

    if args.print_kv_origin:
        client = build_kv_client(env)
        origin_key = env.get("CLOUDFLARE_KV_ORIGIN_KEY") or DEFAULT_ORIGIN_KEY
        print(client.get_value(origin_key) or "")
        return 0

    interval = float(env.get("SENTINEL_INTERVAL_SECONDS") or "30")
    if not args.loop and not args.once:
        args.once = True

    while True:
        try:
            run_once(root, env)
        except Exception as error:
            log(f"sentinel reconciliation failed: {error}")
        if args.once:
            return 0
        time.sleep(interval)


if __name__ == "__main__":
    raise SystemExit(main())
