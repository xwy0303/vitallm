#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"
inventory="${1:-${VITALAB_INVENTORY:-}}"
service="${2:-}"
tail_count="${3:-100}"
load_inventory "${inventory}"

root_q="$(shell_quote "${VITALAB_ROOT}")"
service_q="$(shell_quote "${service}")"
tail_q="$(shell_quote "${tail_count}")"
profiles_q="$(shell_quote "${VITALAB_COMPOSE_PROFILES}")"

ssh_remote_bash <<EOF
set -euo pipefail
VITALAB_ROOT=${root_q}
SERVICE=${service_q}
TAIL_COUNT=${tail_q}
VITALAB_COMPOSE_PROFILES=${profiles_q}
cd "\${VITALAB_ROOT}/deploy"

if [[ "\${SERVICE}" == "sentinel" || "\${SERVICE}" == "quick-tunnel-sentinel" || "\${SERVICE}" == "vitalab-quick-tunnel-sentinel" ]]; then
  if command -v journalctl >/dev/null 2>&1; then
    journalctl --user -u vitalab-quick-tunnel-sentinel.service -n "\${TAIL_COUNT}" --no-pager 2>/dev/null ||
      journalctl -u vitalab-quick-tunnel-sentinel.service -n "\${TAIL_COUNT}" --no-pager 2>/dev/null ||
      true
  fi
  if [[ -f "\${VITALAB_ROOT}/logs/quick-tunnel-sentinel.stdout.log" ]]; then
    echo "== launchd stdout =="
    tail -n "\${TAIL_COUNT}" "\${VITALAB_ROOT}/logs/quick-tunnel-sentinel.stdout.log"
  fi
  if [[ -f "\${VITALAB_ROOT}/logs/quick-tunnel-sentinel.stderr.log" ]]; then
    echo "== launchd stderr =="
    tail -n "\${TAIL_COUNT}" "\${VITALAB_ROOT}/logs/quick-tunnel-sentinel.stderr.log"
  fi
  exit 0
fi

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

if [[ -n "\${SERVICE}" ]]; then
  compose_cmd --env-file ../config/runtime.env "\${profile_args[@]}" -f compose.yaml logs --tail "\${TAIL_COUNT}" "\${SERVICE}"
else
  compose_cmd --env-file ../config/runtime.env "\${profile_args[@]}" -f compose.yaml logs --tail "\${TAIL_COUNT}"
fi
EOF
