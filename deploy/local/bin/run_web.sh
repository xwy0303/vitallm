#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"
load_local_env
ensure_log_dir

WEB_HOST="${SHENGJI_WEB_HOST:-127.0.0.1}"
WEB_PORT="${SHENGJI_WEB_PORT:-5173}"
PYTHON_BIN="${SHENGJI_PYTHON_BIN:-$(command -v python3)}"

if [[ -z "${PYTHON_BIN}" || ! -x "${PYTHON_BIN}" ]]; then
  echo "python3 executable not found. Set SHENGJI_PYTHON_BIN in deploy/local/env.local." >&2
  exit 1
fi

cd "${PROJECT_DIR}"

exec "${PYTHON_BIN}" -m http.server "${WEB_PORT}" --bind "${WEB_HOST}" -d web
