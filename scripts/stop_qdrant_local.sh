#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PID_FILE="${ROOT_DIR}/.local/qdrant/qdrant.pid"

if [[ ! -f "${PID_FILE}" ]]; then
  echo "Qdrant pid file not found; nothing to stop."
  exit 0
fi

PID="$(cat "${PID_FILE}")"
if ps -p "${PID}" >/dev/null 2>&1; then
  kill "${PID}"
  echo "Qdrant stopped: pid=${PID}"
else
  echo "Qdrant process not running: pid=${PID}"
fi

rm -f "${PID_FILE}"
