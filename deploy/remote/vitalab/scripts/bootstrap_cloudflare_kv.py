#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from quick_tunnel_sentinel import DEFAULT_ORIGIN_KEY, normalize_backend_origin, parse_env_file


API_BASE = "https://api.cloudflare.com/client/v4"


def request_json(method: str, url: str, token: str, payload: dict | None = None) -> dict:
    data = None
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Cloudflare API HTTP {error.code}: {body[:400]}") from error


def put_kv_value(account_id: str, namespace_id: str, key: str, value: str, token: str) -> None:
    encoded_key = urllib.parse.quote(key, safe="")
    url = f"{API_BASE}/accounts/{account_id}/storage/kv/namespaces/{namespace_id}/values/{encoded_key}"
    request = urllib.request.Request(
        url,
        data=value.encode("utf-8"),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "text/plain; charset=utf-8"},
        method="PUT",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            response.read()
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Cloudflare KV write HTTP {error.code}: {body[:400]}") from error


def find_namespace(account_id: str, token: str, title: str) -> str | None:
    url = f"{API_BASE}/accounts/{account_id}/storage/kv/namespaces?per_page=100"
    payload = request_json("GET", url, token)
    for namespace in payload.get("result") or []:
        if namespace.get("title") == title:
            return namespace.get("id")
    return None


def create_namespace(account_id: str, token: str, title: str) -> str:
    url = f"{API_BASE}/accounts/{account_id}/storage/kv/namespaces"
    payload = request_json("POST", url, token, {"title": title})
    namespace_id = (payload.get("result") or {}).get("id")
    if not namespace_id:
        raise RuntimeError("Cloudflare did not return a KV namespace id")
    return namespace_id


def load_env(inventory: Path | None, root: Path | None) -> dict[str, str]:
    env: dict[str, str] = {}
    if inventory:
        env.update(parse_env_file(inventory))
    if root:
        env.update(parse_env_file(root / "config" / "runtime.env"))
        env.update(parse_env_file(root / "secrets" / "cloudflare.env"))
    env.update({key: value for key, value in os.environ.items() if key.startswith("CLOUDFLARE_")})
    return env


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create/reuse Vitalab Cloudflare KV namespace and seed backend origin.")
    parser.add_argument("inventory", nargs="?", type=Path, help="Optional inventory env file.")
    parser.add_argument("--root", type=Path, help="Optional deployed VITALAB_ROOT for runtime/secrets env.")
    parser.add_argument("--initial-origin", help="Optional backend origin to write to KV.")
    args = parser.parse_args(argv)

    env = load_env(args.inventory, args.root)
    account_id = env.get("CLOUDFLARE_ACCOUNT_ID")
    token = env.get("CLOUDFLARE_API_TOKEN")
    if not account_id or not token:
        raise SystemExit("CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN are required")

    namespace_title = env.get("CLOUDFLARE_KV_NAMESPACE_TITLE") or "vitalab-origin-registry"
    namespace_id = env.get("CLOUDFLARE_KV_NAMESPACE_ID") or find_namespace(account_id, token, namespace_title)
    if not namespace_id:
        namespace_id = create_namespace(account_id, token, namespace_title)

    origin_key = env.get("CLOUDFLARE_KV_ORIGIN_KEY") or DEFAULT_ORIGIN_KEY
    initial_origin = args.initial_origin or env.get("CLOUDFLARE_INITIAL_BACKEND_ORIGIN")
    if initial_origin:
        normalized = normalize_backend_origin(initial_origin)
        if not normalized:
            raise SystemExit("initial origin must be https://*.trycloudflare.com")
        put_kv_value(account_id, namespace_id, origin_key, normalized, token)
        print(f"seeded {origin_key}={normalized}")

    print(f"CLOUDFLARE_KV_NAMESPACE_ID={namespace_id}")
    print("Use this namespace id in inventory/runtime before running deploy_pages.sh.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
