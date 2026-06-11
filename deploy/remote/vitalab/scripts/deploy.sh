#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"
load_inventory "${1:-${VITALAB_INVENTORY:-}}"

profiles_q="$(shell_quote "${VITALAB_COMPOSE_PROFILES}")"
project_q="$(shell_quote "${VITALAB_COMPOSE_PROJECT}")"
root_q="$(shell_quote "${VITALAB_ROOT}")"

ssh_remote_bash <<EOF
set -euo pipefail
VITALAB_ROOT=${root_q}
COMPOSE_PROJECT_NAME=${project_q}
VITALAB_COMPOSE_PROFILES=${profiles_q}
if [[ -f "\${VITALAB_ROOT}/config/runtime.env" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "\${VITALAB_ROOT}/config/runtime.env"
  set +a
fi
cd "\${VITALAB_ROOT}/deploy"

compose_cmd() {
  if docker compose version >/dev/null 2>&1; then
    docker compose "\$@"
  elif command -v docker-compose >/dev/null 2>&1; then
    docker-compose "\$@"
  else
    echo "docker compose is required" >&2
    exit 1
  fi
}

profile_args=()
for profile in \${VITALAB_COMPOSE_PROFILES//,/ }; do
  [[ -n "\${profile}" ]] || continue
  profile_args+=(--profile "\${profile}")
done

listen_occupied() {
  local host_port="\$1"
  if command -v ss >/dev/null 2>&1; then
    ss -ltnp 2>/dev/null | awk -v p=":\${host_port}" '\$4 ~ p"$" {print}' || true
  elif command -v lsof >/dev/null 2>&1; then
    lsof -nP -iTCP:"\${host_port}" -sTCP:LISTEN 2>/dev/null || true
  fi
}

check_host_port() {
  local service="\$1"
  local container_port="\$2"
  local host_port="\$3"
  local container occupied owns_port

  container="\$(compose_cmd --env-file ../config/runtime.env "\${profile_args[@]}" -f compose.yaml ps -q "\${service}" 2>/dev/null || true)"
  occupied="\$(listen_occupied "\${host_port}")"
  if [[ -z "\${occupied}" ]]; then
    return 0
  fi

  owns_port="false"
  if [[ -n "\${container}" ]]; then
    if docker port "\${container}" "\${container_port}/tcp" 2>/dev/null | grep -Eq "(^|:)\${host_port}\$"; then
      owns_port="true"
    fi
  fi
  if [[ "\${owns_port}" != "true" ]]; then
    echo "ERROR: 127.0.0.1:\${host_port} is already occupied; not killing unknown process." >&2
    echo "\${occupied}" >&2
    exit 1
  fi
}

check_host_port api 8001 "\${ENZYME_API_PORT:-18081}"
check_host_port web 80 "\${SHENGJI_WEB_PORT:-5173}"

compose_cmd --env-file ../config/runtime.env "\${profile_args[@]}" -f compose.yaml up -d --build
compose_cmd --env-file ../config/runtime.env "\${profile_args[@]}" -f compose.yaml ps
EOF
