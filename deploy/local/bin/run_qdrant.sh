#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"
load_local_env
ensure_log_dir

QDRANT_BIN="${PROJECT_DIR}/.local/qdrant/qdrant"
QDRANT_STORAGE="${PROJECT_DIR}/.local/qdrant/storage"
QDRANT_HTTP_PORT="${QDRANT_HTTP_PORT:-6333}"
QDRANT_GRPC_PORT="${QDRANT_GRPC_PORT:-6334}"

if [[ ! -x "${QDRANT_BIN}" ]]; then
  echo "Qdrant binary not found or not executable: ${QDRANT_BIN}" >&2
  exit 1
fi

mkdir -p "${QDRANT_STORAGE}"
cd "${PROJECT_DIR}"

exec env \
  QDRANT__STORAGE__STORAGE_PATH="${QDRANT_STORAGE}" \
  QDRANT__SERVICE__HTTP_PORT="${QDRANT_HTTP_PORT}" \
  QDRANT__SERVICE__GRPC_PORT="${QDRANT_GRPC_PORT}" \
  "${QDRANT_BIN}" --disable-telemetry
