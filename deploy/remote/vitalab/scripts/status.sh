#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"
load_inventory "${1:-${VITALAB_INVENTORY:-}}"

root_q="$(shell_quote "${VITALAB_ROOT}")"
profiles_q="$(shell_quote "${VITALAB_COMPOSE_PROFILES}")"

ssh_remote_bash <<EOF
set -euo pipefail
VITALAB_ROOT=${root_q}
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
    return 127
  fi
}

profile_args=()
for profile in \${VITALAB_COMPOSE_PROFILES//,/ }; do
  [[ -n "\${profile}" ]] || continue
  profile_args+=(--profile "\${profile}")
done

if compose_cmd ps >/dev/null 2>&1; then
  compose_cmd --env-file ../config/runtime.env "\${profile_args[@]}" -f compose.yaml ps
else
  echo "docker compose status unavailable"
fi

echo "== local health =="
curl -fsS "http://127.0.0.1:\${ENZYME_API_PORT:-18081}/api/health" || true
echo
curl -fsS "http://127.0.0.1:\${SHENGJI_WEB_PORT:-5173}/api/health" || true
echo
curl -fsS "http://127.0.0.1:\${QDRANT_HTTP_PORT:-6333}/collections" || true
echo
EOF
