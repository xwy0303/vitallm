#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/bin/common.sh"
load_local_env

APP_ROOT="${HOME}/Library/Application Support/Shengji/app"
INCLUDE_DATA=false
if [[ "${1:-}" == "--include-data" ]]; then
  INCLUDE_DATA=true
fi
PATHS=(
  src
  web
  configs
  schemas
  scripts
)
DATA_PATHS=(artifacts .local .venv .venv-mineru "MOF固定化脂肪酶文献调研")

sync_path() {
  local path="$1"
  local source="${PROJECT_DIR}/${path}"
  local target="${APP_ROOT}/${path}"
  if [[ ! -e "${source}" ]]; then
    return
  fi
  mkdir -p "$(dirname "${target}")"
  ditto "${source}" "${target}"
}

mkdir -p "${APP_ROOT}"
for path in "${PATHS[@]}"; do
  sync_path "${path}"
done
if [[ "${INCLUDE_DATA}" == "true" ]]; then
  for path in "${DATA_PATHS[@]}"; do
    sync_path "${path}"
  done
fi

mkdir -p "${APP_ROOT}/deploy/local"
if [[ -f "${PROJECT_DIR}/deploy/local/env.local" ]]; then
  install -m 600 "${PROJECT_DIR}/deploy/local/env.local" "${APP_ROOT}/deploy/local/env.local"
fi
if [[ -f "${PROJECT_DIR}/.env.local" ]]; then
  install -m 600 "${PROJECT_DIR}/.env.local" "${APP_ROOT}/.env.local"
fi

if [[ "${INCLUDE_DATA}" == "true" ]]; then
  echo "Synced runtime mirror including data: ${APP_ROOT}"
else
  echo "Synced runtime code/config only: ${APP_ROOT}"
fi
