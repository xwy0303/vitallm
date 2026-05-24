#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"
load_local_env
ensure_log_dir

max_bytes="${SHENGJI_LOG_MAX_BYTES:-52428800}"
retention_days="${SHENGJI_LOG_RETENTION_DAYS:-14}"
timestamp="$(date +%Y%m%d-%H%M%S)"

for file in "${LOG_DIR}"/*.log; do
  [[ -f "${file}" ]] || continue
  size="$(stat -f '%z' "${file}")"
  if (( size >= max_bytes )); then
    rotated="${file}.${timestamp}"
    cp "${file}" "${rotated}"
    gzip -f "${rotated}"
    : > "${file}"
  fi
done

find "${LOG_DIR}" -name '*.gz' -type f -mtime +"${retention_days}" -delete
