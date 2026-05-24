#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/bin/common.sh"

AGENT_DIR="${HOME}/Library/LaunchAgents"
UID_VALUE="$(id -u)"
labels=(
  com.shengji.qdrant
  com.shengji.mineru
  com.shengji.api
  com.shengji.web
  com.shengji.logrotate
)

for label in "${labels[@]}"; do
  plist="${AGENT_DIR}/${label}.plist"
  launchctl bootout "gui/${UID_VALUE}" "${plist}" >/dev/null 2>&1 || true
  rm -f "${plist}"
  echo "Removed ${label}"
done

echo "LaunchAgents removed. Logs, storage, artifacts, PDFs, and model caches were not deleted."
