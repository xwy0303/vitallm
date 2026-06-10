#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"
load_inventory "${1:-${VITALAB_INVENTORY:-}}"

os_value="$(remote_os)"
echo "Remote OS: ${os_value}"

root_q="$(shell_quote "${VITALAB_ROOT}")"
project_q="$(shell_quote "${VITALAB_COMPOSE_PROJECT}")"

ssh_remote_bash <<EOF
set -euo pipefail
VITALAB_ROOT=${root_q}
COMPOSE_PROJECT_NAME=${project_q}

mkdir -p "\${VITALAB_ROOT}"/{app,config,secrets,data/qdrant,data/snapshots,data/model_cache,data/pdfs,artifacts,logs,deploy}
chmod 700 "\${VITALAB_ROOT}/secrets"
touch "\${VITALAB_ROOT}/secrets/api.env"
chmod 600 "\${VITALAB_ROOT}/secrets/api.env"

echo "== host =="
hostname || true
uname -a || true

echo "== runtime =="
if command -v docker >/dev/null 2>&1; then
  docker --version
else
  echo "docker: missing"
fi

if docker compose version >/dev/null 2>&1; then
  docker compose version
elif command -v docker-compose >/dev/null 2>&1; then
  docker-compose version
else
  echo "docker compose: missing"
fi

if command -v systemctl >/dev/null 2>&1; then
  echo "systemd: available"
fi
if command -v launchctl >/dev/null 2>&1; then
  echo "launchd: available"
fi
if command -v nvidia-smi >/dev/null 2>&1; then
  nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader || true
else
  echo "nvidia-smi: missing"
fi

echo "Bootstrap directory ready: \${VITALAB_ROOT}"
EOF
