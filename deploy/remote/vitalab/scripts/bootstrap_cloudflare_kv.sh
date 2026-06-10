#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"
inventory="${1:-${VITALAB_INVENTORY:-}}"
load_inventory "${inventory}"

python3 "${SCRIPT_DIR}/bootstrap_cloudflare_kv.py" "${inventory}"
