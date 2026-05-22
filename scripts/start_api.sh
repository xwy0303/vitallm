#!/usr/bin/env bash
set -euo pipefail

HOST="${ENZYME_API_HOST:-127.0.0.1}"
PORT="${ENZYME_API_PORT:-8001}"
CONFIG="${ENZYME_RUNTIME_CONFIG:-configs/local.yaml}"
RELOAD="${ENZYME_API_RELOAD:-0}"

args=(
  enzyme_recommender.api.app:app
  --host "${HOST}"
  --port "${PORT}"
  --app-dir .
)

if [[ "${RELOAD}" == "1" ]]; then
  args+=(--reload)
fi

PYTHONPATH=src ENZYME_RUNTIME_CONFIG="${CONFIG}" .venv/bin/uvicorn "${args[@]}"
