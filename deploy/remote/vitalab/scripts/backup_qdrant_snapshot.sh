#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"
inventory="${1:-${VITALAB_INVENTORY:-}}"
collection="${2:-enzyme_immobilization_literature_sentence_baai_bge_base_en_v1_5_768_point_schema_v1}"
load_inventory "${inventory}"

root_q="$(shell_quote "${VITALAB_ROOT}")"
collection_q="$(shell_quote "${collection}")"

ssh_remote_bash <<EOF
set -euo pipefail
VITALAB_ROOT=${root_q}
COLLECTION=${collection_q}
if [[ -f "\${VITALAB_ROOT}/config/runtime.env" ]]; then
  set -a
  source "\${VITALAB_ROOT}/config/runtime.env"
  set +a
fi
QDRANT_PORT="\${QDRANT_HTTP_PORT:-6333}"
mkdir -p "\${VITALAB_ROOT}/data/snapshots"
echo "Creating Qdrant snapshot for collection: \${COLLECTION}"
curl -fsS -X POST "http://127.0.0.1:\${QDRANT_PORT}/collections/\${COLLECTION}/snapshots"
echo
echo "Available snapshots:"
curl -fsS "http://127.0.0.1:\${QDRANT_PORT}/collections/\${COLLECTION}/snapshots"
echo
EOF
