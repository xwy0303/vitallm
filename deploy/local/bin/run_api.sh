#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"
load_local_env
ensure_log_dir

QDRANT_HTTP_PORT="${QDRANT_HTTP_PORT:-6333}"
ENZYME_API_HOST="${ENZYME_API_HOST:-127.0.0.1}"
ENZYME_API_PORT="${ENZYME_API_PORT:-8001}"
ENZYME_RUNTIME_CONFIG="${ENZYME_RUNTIME_CONFIG:-configs/local.yaml}"

wait_for_http "http://127.0.0.1:${QDRANT_HTTP_PORT}/collections" 60

cd "${PROJECT_DIR}"

exec env \
  ENZYME_API_HOST="${ENZYME_API_HOST}" \
  ENZYME_API_PORT="${ENZYME_API_PORT}" \
  ENZYME_RUNTIME_CONFIG="${ENZYME_RUNTIME_CONFIG}" \
  scripts/start_api.sh
