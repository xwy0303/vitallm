#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"
inventory="${1:-${VITALAB_INVENTORY:-}}"
snapshot_url="${2:-}"
collection="${3:-enzyme_immobilization_literature_sentence_baai_bge_base_en_v1_5_768_point_schema_v1}"
load_inventory "${inventory}"

[[ -n "${snapshot_url}" ]] || die "snapshot URL/path required as second argument"
[[ "${RESTORE_CONFIRM:-}" == "I_UNDERSTAND_QDRANT_RESTORE" ]] || die "set RESTORE_CONFIRM=I_UNDERSTAND_QDRANT_RESTORE to run restore"

root_q="$(shell_quote "${VITALAB_ROOT}")"
snapshot_q="$(shell_quote "${snapshot_url}")"
collection_q="$(shell_quote "${collection}")"

ssh_remote_bash <<EOF
set -euo pipefail
VITALAB_ROOT=${root_q}
SNAPSHOT_URL=${snapshot_q}
COLLECTION=${collection_q}
if [[ -f "\${VITALAB_ROOT}/config/runtime.env" ]]; then
  set -a
  source "\${VITALAB_ROOT}/config/runtime.env"
  set +a
fi
QDRANT_PORT="\${QDRANT_HTTP_PORT:-6333}"
echo "Restoring Qdrant collection \${COLLECTION} from \${SNAPSHOT_URL}"
curl -fsS -X PUT \
  "http://127.0.0.1:\${QDRANT_PORT}/collections/\${COLLECTION}/snapshots/recover" \
  -H 'Content-Type: application/json' \
  --data "{\"location\":\"\${SNAPSHOT_URL}\"}"
echo
EOF
