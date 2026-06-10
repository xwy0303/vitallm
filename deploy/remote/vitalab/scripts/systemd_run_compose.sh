#!/usr/bin/env bash
set -euo pipefail

action="${1:-up}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
ROOT_DIR="$(cd "${DEPLOY_DIR}/.." && pwd)"

cd "${DEPLOY_DIR}"

if [[ -f "${ROOT_DIR}/config/runtime.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${ROOT_DIR}/config/runtime.env"
  set +a
fi

compose_cmd() {
  if docker compose version >/dev/null 2>&1; then
    docker compose "$@"
  elif command -v docker-compose >/dev/null 2>&1; then
    docker-compose "$@"
  else
    echo "docker compose is required" >&2
    exit 1
  fi
}

profile_args=()
profiles="${VITALAB_COMPOSE_PROFILES:-quick-tunnel}"
for profile in ${profiles//,/ }; do
  [[ -n "${profile}" ]] || continue
  profile_args+=(--profile "${profile}")
done

case "${action}" in
  up|start)
    compose_cmd --env-file "${ROOT_DIR}/config/runtime.env" "${profile_args[@]}" -f "${DEPLOY_DIR}/compose.yaml" up -d
    ;;
  down|stop)
    compose_cmd --env-file "${ROOT_DIR}/config/runtime.env" "${profile_args[@]}" -f "${DEPLOY_DIR}/compose.yaml" down
    ;;
  *)
    echo "Usage: systemd_run_compose.sh <up|down>" >&2
    exit 2
    ;;
esac
