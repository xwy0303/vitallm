#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/bin/common.sh"
load_local_env

UID_VALUE="$(id -u)"
labels=(
  com.shengji.qdrant
  com.shengji.mineru
  com.shengji.api
  com.shengji.ingestion-worker
  com.shengji.web
  com.shengji.logrotate
)

for label in "${labels[@]}"; do
  echo "== ${label} =="
  if launchctl print "gui/${UID_VALUE}/${label}" >/dev/null 2>&1; then
    launchctl print "gui/${UID_VALUE}/${label}" | awk '/state =|last exit code =|pid =|program =/'
  else
    echo "not loaded"
  fi
  echo
done

echo "== health checks =="
checks=(
  "qdrant http://127.0.0.1:${QDRANT_HTTP_PORT:-6333}/collections"
  "mineru http://127.0.0.1:${MINERU_PORT:-8000}/health"
  "api http://127.0.0.1:${ENZYME_API_PORT:-8001}/api/health"
  "web http://127.0.0.1:${SHENGJI_WEB_PORT:-5173}/"
)

for item in "${checks[@]}"; do
  name="${item%% *}"
  url="${item#* }"
  if curl -fsS "${url}" >/dev/null 2>&1; then
    echo "${name}: ok"
  elif [[ "${url}" =~ :([0-9]+)/? ]]; then
    port="${BASH_REMATCH[1]}"
    if lsof -n -P -iTCP:"${port}" -sTCP:LISTEN >/dev/null 2>&1; then
      echo "${name}: listening, http check unavailable (${url})"
    else
      echo "${name}: unavailable (${url})"
    fi
  else
    echo "${name}: unavailable (${url})"
  fi
done
