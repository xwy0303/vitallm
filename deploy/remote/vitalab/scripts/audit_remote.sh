#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"
load_inventory "${1:-${VITALAB_INVENTORY:-}}"

root_q="$(shell_quote "${VITALAB_ROOT}")"

ssh_remote_bash <<EOF
set -euo pipefail
VITALAB_ROOT=${root_q}

echo "== identity =="
hostname || true
whoami || true
pwd || true
uname -a || true

echo "== directories =="
mkdir -p "\${VITALAB_ROOT}"
test -w "\${VITALAB_ROOT}" && echo "VITALAB_ROOT writable: \${VITALAB_ROOT}" || echo "VITALAB_ROOT not writable: \${VITALAB_ROOT}"

echo "== cpu/memory/disk =="
if command -v lscpu >/dev/null 2>&1; then lscpu | sed -n '1,24p'; fi
if command -v free >/dev/null 2>&1; then free -h; fi
df -h "\${VITALAB_ROOT}" || df -h .

echo "== docker =="
if command -v docker >/dev/null 2>&1; then
  docker --version
  docker info --format '{{json .ServerVersion}}' 2>/dev/null || echo "docker daemon unavailable"
else
  echo "docker missing"
fi
if docker compose version >/dev/null 2>&1; then
  docker compose version
elif command -v docker-compose >/dev/null 2>&1; then
  docker-compose version
else
  echo "docker compose missing"
fi

echo "== service manager =="
if command -v systemctl >/dev/null 2>&1; then
  echo "systemd available"
  systemctl --version | sed -n '1,2p'
fi
if command -v launchctl >/dev/null 2>&1; then
  echo "launchd available"
fi

echo "== gpu =="
if command -v nvidia-smi >/dev/null 2>&1; then
  nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader || true
else
  echo "nvidia-smi missing"
fi

echo "== network =="
if command -v curl >/dev/null 2>&1; then
  curl -fsS --max-time 8 https://api.cloudflare.com/client/v4 >/dev/null && echo "cloudflare reachable" || echo "cloudflare check failed"
  curl -fsS --max-time 8 https://api.siliconflow.cn/v1 >/dev/null && echo "siliconflow reachable" || echo "siliconflow check failed"
else
  echo "curl missing"
fi
EOF
