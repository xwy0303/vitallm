#!/usr/bin/env bash
set -euo pipefail

resolve_project_dir() {
  if [[ -n "${SHENGJI_PROJECT_DIR:-}" ]]; then
    printf '%s\n' "${SHENGJI_PROJECT_DIR}"
    return
  fi
  local script_dir
  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  cd "${script_dir}/../../.." && pwd
}

refresh_runtime_paths() {
  PROJECT_DIR="$(resolve_project_dir)"
  DEPLOY_DIR="${PROJECT_DIR}/deploy/local"
  LOG_DIR="${SHENGJI_LOG_DIR:-${HOME}/Library/Logs/Shengji}"
}

refresh_runtime_paths

load_local_env() {
  if [[ -f "${DEPLOY_DIR}/env.local" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "${DEPLOY_DIR}/env.local"
    set +a
    refresh_runtime_paths
  fi
}

ensure_log_dir() {
  mkdir -p "${LOG_DIR}"
}

wait_for_http() {
  local url="$1"
  local timeout_seconds="${2:-60}"
  local started_at
  started_at="$(date +%s)"
  until curl -fsS "${url}" >/dev/null 2>&1; do
    if (( "$(date +%s)" - started_at >= timeout_seconds )); then
      echo "Timed out waiting for ${url}" >&2
      return 1
    fi
    sleep 1
  done
}
