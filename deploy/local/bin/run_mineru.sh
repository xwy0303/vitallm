#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"
load_local_env
ensure_log_dir

MINERU_BIN="${PROJECT_DIR}/.venv-mineru/bin/mineru-api"
MINERU_HOST="${MINERU_HOST:-127.0.0.1}"
MINERU_PORT="${MINERU_PORT:-8000}"
MINERU_ENABLE_VLM_PRELOAD="${MINERU_ENABLE_VLM_PRELOAD:-false}"

if [[ ! -x "${MINERU_BIN}" ]]; then
  echo "MinerU API binary not found or not executable: ${MINERU_BIN}" >&2
  exit 1
fi

cd "${PROJECT_DIR}"

exec "${MINERU_BIN}" \
  --host "${MINERU_HOST}" \
  --port "${MINERU_PORT}" \
  --enable-vlm-preload "${MINERU_ENABLE_VLM_PRELOAD}"
