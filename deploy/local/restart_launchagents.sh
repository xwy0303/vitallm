#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/bin/common.sh"

UID_VALUE="$(id -u)"

usage() {
  cat <<'EOF'
Usage:
  deploy/local/restart_launchagents.sh <service|all>

Services:
  qdrant mineru api web logrotate all
EOF
}

label_for_service() {
  case "$1" in
    qdrant|mineru|api|web|logrotate) printf 'com.shengji.%s\n' "$1" ;;
    *) return 1 ;;
  esac
}

target="${1:-}"
if [[ -z "${target}" || "${target}" == "--help" || "${target}" == "-h" ]]; then
  usage
  exit 0
fi

if [[ "${target}" == "all" ]]; then
  services=(qdrant mineru api web logrotate)
else
  services=("${target}")
fi

for service in "${services[@]}"; do
  label="$(label_for_service "${service}")" || {
    echo "Unknown service: ${service}" >&2
    usage >&2
    exit 1
  }
  launchctl kickstart -k "gui/${UID_VALUE}/${label}"
  echo "Restarted ${label}"
done
