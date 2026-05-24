#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"
load_local_env

ports=(
  "${MINERU_PORT:-8000}"
  "${QDRANT_HTTP_PORT:-6333}"
  "${QDRANT_GRPC_PORT:-6334}"
  "${ENZYME_API_PORT:-8001}"
  "${SHENGJI_WEB_PORT:-5173}"
)

if ! command -v lsof >/dev/null 2>&1; then
  echo "lsof is required for port checks." >&2
  exit 1
fi

blocked=0
for port in "${ports[@]}"; do
  if lsof -n -P -iTCP:"${port}" -sTCP:LISTEN >/tmp/shengji-port-"${port}".txt 2>/dev/null; then
    echo "Port ${port} is already in use:" >&2
    cat /tmp/shengji-port-"${port}".txt >&2
    blocked=1
  fi
  rm -f /tmp/shengji-port-"${port}".txt
done

if [[ "${blocked}" == "1" ]]; then
  echo "Stop the conflicting process before installing LaunchAgents." >&2
  exit 1
fi

echo "Required ports are free."
