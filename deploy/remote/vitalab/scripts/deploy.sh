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

API_PORT="\${ENZYME_API_PORT:-18001}"
api_container="\$(compose_cmd --env-file ../config/runtime.env "\${profile_args[@]}" -f compose.yaml ps -q api 2>/dev/null || true)"
if command -v ss >/dev/null 2>&1; then
  occupied="\$(ss -ltnp 2>/dev/null | awk -v p=":\${API_PORT}" '\$4 ~ p"$" {print}' || true)"
elif command -v lsof >/dev/null 2>&1; then
  occupied="\$(lsof -nP -iTCP:"\${API_PORT}" -sTCP:LISTEN 2>/dev/null || true)"
else
  occupied=""
fi
if [[ -n "\${occupied}" ]]; then
  owns_port="false"
  if [[ -n "\${api_container}" ]]; then
    if docker port "\${api_container}" 8001/tcp 2>/dev/null | grep -Eq "(^|:)\${API_PORT}\$"; then
      owns_port="true"
    fi
  fi
  if [[ "\${owns_port}" != "true" ]]; then
    echo "ERROR: 127.0.0.1:\${API_PORT} is already occupied; not killing unknown process." >&2
    echo "\${occupied}" >&2
    exit 1
  fi
fi

compose_cmd --env-file ../config/runtime.env "\${profile_args[@]}" -f compose.yaml up -d --build
compose_cmd --env-file ../config/runtime.env "\${profile_args[@]}" -f compose.yaml ps
EOF
