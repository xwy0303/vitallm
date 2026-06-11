#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"
load_inventory "${1:-${VITALAB_INVENTORY:-}}"

root_q="$(shell_quote "${VITALAB_ROOT}")"
pages_url_q="$(shell_quote "${CLOUDFLARE_PAGES_URL}")"

ssh_remote_bash <<EOF
set -euo pipefail
VITALAB_ROOT=${root_q}
CLOUDFLARE_PAGES_URL=${pages_url_q}
if [[ -f "\${VITALAB_ROOT}/config/runtime.env" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "\${VITALAB_ROOT}/config/runtime.env"
  set +a
fi

API_PORT="\${ENZYME_API_PORT:-18081}"
QDRANT_PORT="\${QDRANT_HTTP_PORT:-6333}"
WEB_PORT="\${SHENGJI_WEB_PORT:-5173}"
if command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN=python3
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN=python
else
  echo "python3 or python is required for JSON verification" >&2
  exit 1
fi

echo "== API health =="
curl -fsS "http://127.0.0.1:\${API_PORT}/api/health"
echo

echo "== web same-origin API health =="
curl -fsS "http://127.0.0.1:\${WEB_PORT}/api/health"
echo

echo "== documents =="
curl -fsS "http://127.0.0.1:\${API_PORT}/api/documents" | "\${PYTHON_BIN}" -c 'import json,sys; d=json.load(sys.stdin); print({"collection": d.get("collection"), "document_count": len(d.get("documents") or [])})'

echo "== dashboard =="
curl -fsS "http://127.0.0.1:\${API_PORT}/api/dashboard/summary" | "\${PYTHON_BIN}" -c 'import json,sys; d=json.load(sys.stdin); keys=["source_pdf_count","processed_docs","processed_pages","qdrant_points","qdrant_status","collection"]; print({k:d.get(k) for k in keys})'

echo "== qdrant collections =="
curl -fsS "http://127.0.0.1:\${QDRANT_PORT}/collections"
echo

if [[ -f "\${VITALAB_ROOT}/config/current_backend_origin" ]]; then
  ORIGIN="\$(cat "\${VITALAB_ROOT}/config/current_backend_origin" | tr -d '[:space:]')"
  if [[ -n "\${ORIGIN}" ]]; then
    echo "== tunnel origin health =="
    curl -fsS "\${ORIGIN}/api/health"
    echo
  fi
fi

if [[ -f "\${VITALAB_ROOT}/secrets/cloudflare.env" ]]; then
  echo "== KV origin =="
  PYTHONPATH="\${VITALAB_ROOT}/deploy/scripts" "\${PYTHON_BIN}" "\${VITALAB_ROOT}/deploy/scripts/quick_tunnel_sentinel.py" --root "\${VITALAB_ROOT}" --print-kv-origin
  echo
else
  echo "== KV origin =="
  echo "skipped: \${VITALAB_ROOT}/secrets/cloudflare.env not found"
fi

if [[ -n "\${CLOUDFLARE_PAGES_URL}" ]]; then
  echo "== Pages proxy health =="
  curl -fsS "\${CLOUDFLARE_PAGES_URL%/}/api/health"
  echo
fi
EOF
