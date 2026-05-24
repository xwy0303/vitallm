#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"
load_local_env

usage() {
  cat <<'EOF'
Usage:
  deploy/local/bin/logs.sh <service|all> [--tail N] [--follow]

Services:
  qdrant mineru api web logrotate all
EOF
}

service="${1:-}"
shift || true

tail_lines="100"
follow="0"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --tail)
      tail_lines="${2:-100}"
      shift 2
      ;;
    --follow|-f)
      follow="1"
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if [[ -z "${service}" ]]; then
  usage >&2
  exit 1
fi

if [[ "${service}" == "all" ]]; then
  files=("${LOG_DIR}"/*.log)
else
  files=("${LOG_DIR}/${service}.stdout.log" "${LOG_DIR}/${service}.stderr.log")
fi

existing=()
for file in "${files[@]}"; do
  if [[ -f "${file}" ]]; then
    existing+=("${file}")
  fi
done

if [[ "${#existing[@]}" -eq 0 ]]; then
  echo "No log files found for '${service}' under ${LOG_DIR}." >&2
  exit 1
fi

if [[ "${follow}" == "1" ]]; then
  exec tail -n "${tail_lines}" -F "${existing[@]}"
fi

exec tail -n "${tail_lines}" "${existing[@]}"
