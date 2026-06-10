#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"
load_inventory "${1:-${VITALAB_INVENTORY:-}}"

ssh_cmd="$(rsync_ssh_cmd)"
delete_args=()
if [[ "${SYNC_DELETE}" == "true" ]]; then
  delete_args+=("--delete")
fi

rsync_path() {
  local source="$1"
  local target="$2"
  [[ -e "${PROJECT_DIR}/${source}" ]] || return 0
  local remote_target
  remote_target="$(shell_quote "${target}")"
  rsync -az "${delete_args[@]}" -e "${ssh_cmd}" "${PROJECT_DIR}/${source}" "${SSH_TARGET}:${remote_target}"
}

ssh_remote "mkdir -p '${VITALAB_ROOT}/app' '${VITALAB_ROOT}/deploy' '${VITALAB_ROOT}/config' '${VITALAB_ROOT}/secrets' '${VITALAB_ROOT}/artifacts' '${VITALAB_ROOT}/data/pdfs'"

rsync_path "pyproject.toml" "${VITALAB_ROOT}/app/"
for path in src schemas scripts web configs; do
  rsync_path "${path}/" "${VITALAB_ROOT}/app/${path}/"
done

rsync_path "deploy/remote/vitalab/" "${VITALAB_ROOT}/deploy/"

for artifact_path in ${SYNC_ARTIFACT_PATHS}; do
  [[ -e "${PROJECT_DIR}/${artifact_path}" ]] || continue
  target_dir="${VITALAB_ROOT}/$(dirname "${artifact_path}")/"
  ssh_remote "mkdir -p '${target_dir}'"
  rsync_path "${artifact_path}/" "${VITALAB_ROOT}/${artifact_path}/"
done

if [[ "${SYNC_INCLUDE_PDFS}" == "true" && -d "${PROJECT_DIR}/MOF固定化脂肪酶文献调研" ]]; then
  rsync_path "MOF固定化脂肪酶文献调研/" "${VITALAB_ROOT}/data/pdfs/"
fi

ssh_remote_bash <<EOF
set -euo pipefail
cd $(printf "%q" "${VITALAB_ROOT}")
mkdir -p config secrets data/qdrant data/snapshots data/model_cache data/pdfs artifacts logs deploy app
chmod 700 secrets
touch secrets/api.env
chmod 600 secrets/api.env

if [[ ! -f config/runtime.env ]]; then
  cp deploy/runtime.env.example config/runtime.env
fi
if [[ ! -f config/remote.yaml ]]; then
  cp deploy/config/runtime.remote.yaml config/remote.yaml
fi
cp deploy/docker/app.dockerignore .dockerignore
echo "Runtime synced to ${VITALAB_ROOT}"
EOF
