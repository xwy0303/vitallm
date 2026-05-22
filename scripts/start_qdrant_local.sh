#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
QDRANT_BIN="${ROOT_DIR}/.local/qdrant/qdrant"
QDRANT_DIR="${ROOT_DIR}/.local/qdrant"
PID_FILE="${QDRANT_DIR}/qdrant.pid"
LOG_FILE="${QDRANT_DIR}/qdrant.log"

if [[ ! -x "${QDRANT_BIN}" ]]; then
  echo "Qdrant binary not found: ${QDRANT_BIN}" >&2
  echo "Install it under .local/qdrant/qdrant before starting the local service." >&2
  exit 1
fi

mkdir -p "${QDRANT_DIR}/storage"

if [[ -f "${PID_FILE}" ]]; then
  PID="$(cat "${PID_FILE}")"
  if ps -p "${PID}" >/dev/null 2>&1; then
    echo "Qdrant already running: pid=${PID}"
    exit 0
  fi
fi

cd "${ROOT_DIR}"

env \
  QDRANT__STORAGE__STORAGE_PATH="${QDRANT_DIR}/storage" \
  QDRANT__SERVICE__HTTP_PORT=6333 \
  QDRANT__SERVICE__GRPC_PORT=6334 \
  nohup "${QDRANT_BIN}" --disable-telemetry > "${LOG_FILE}" 2>&1 &

echo "$!" > "${PID_FILE}"

for _ in {1..30}; do
  PID="$(cat "${PID_FILE}")"
  if ! ps -p "${PID}" >/dev/null 2>&1; then
    echo "Qdrant exited during startup. Last log lines:" >&2
    tail -40 "${LOG_FILE}" >&2
    exit 1
  fi
  if curl -fsS http://127.0.0.1:6333/collections >/dev/null 2>&1; then
    echo "Qdrant started: pid=${PID} url=http://127.0.0.1:6333"
    exit 0
  fi
  sleep 1
done

echo "Qdrant process started but readiness check timed out. See ${LOG_FILE}" >&2
exit 1
