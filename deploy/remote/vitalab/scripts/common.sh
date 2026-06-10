#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_DIR="$(cd "${DEPLOY_DIR}/../../.." && pwd)"

die() {
  echo "ERROR: $*" >&2
  exit 1
}

usage_inventory() {
  cat <<'EOF'
Usage:
  <script> <inventory.env> [args...]

The inventory file may live outside git. See:
  deploy/remote/vitalab/inventory.example.env
EOF
}

load_inventory() {
  local inventory="${1:-${VITALAB_INVENTORY:-}}"
  if [[ -z "${inventory}" || "${inventory}" == "--help" || "${inventory}" == "-h" ]]; then
    usage_inventory
    exit 0
  fi
  if [[ "${inventory}" != /* ]]; then
    inventory="${PROJECT_DIR}/${inventory}"
  fi
  [[ -f "${inventory}" ]] || die "inventory not found: ${inventory}"

  set -a
  # shellcheck disable=SC1090
  source "${inventory}"
  set +a

  : "${VITALAB_HOST:?missing VITALAB_HOST}"
  : "${VITALAB_USER:?missing VITALAB_USER}"
  : "${VITALAB_ROOT:?missing VITALAB_ROOT}"

  VITALAB_SSH_PORT="${VITALAB_SSH_PORT:-22}"
  VITALAB_REMOTE_OS="${VITALAB_REMOTE_OS:-auto}"
  VITALAB_COMPOSE_PROJECT="${VITALAB_COMPOSE_PROJECT:-vitalab}"
  VITALAB_COMPOSE_PROFILES="${VITALAB_COMPOSE_PROFILES:-quick-tunnel}"
  VITALAB_RUNTIME_ENV="${VITALAB_RUNTIME_ENV:-config/runtime.env}"
  SYNC_DELETE="${SYNC_DELETE:-true}"
  SYNC_INCLUDE_PDFS="${SYNC_INCLUDE_PDFS:-false}"
  SYNC_ARTIFACT_PATHS="${SYNC_ARTIFACT_PATHS:-artifacts/rag_inputs artifacts/evidence artifacts/ingestion_registry artifacts/indexing}"
  TUNNEL_MODE="${TUNNEL_MODE:-quick}"
  CLOUDFLARE_PAGES_URL="${CLOUDFLARE_PAGES_URL:-https://shengji-enzyme-rag-lab.pages.dev}"
  CLOUDFLARE_KV_NAMESPACE_TITLE="${CLOUDFLARE_KV_NAMESPACE_TITLE:-vitalab-origin-registry}"
  CLOUDFLARE_KV_ORIGIN_KEY="${CLOUDFLARE_KV_ORIGIN_KEY:-current_backend_origin}"
  ALLOWED_BACKEND_HOST_SUFFIXES="${ALLOWED_BACKEND_HOST_SUFFIXES:-.trycloudflare.com}"

  SSH_TARGET="${VITALAB_USER}@${VITALAB_HOST}"
  SSH_ARGS=()
  if [[ -n "${VITALAB_SSH_CONFIG:-}" ]]; then
    SSH_ARGS+=("-F" "${VITALAB_SSH_CONFIG}")
  fi
  SSH_ARGS+=("-p" "${VITALAB_SSH_PORT}")
}

ssh_remote() {
  ssh "${SSH_ARGS[@]}" "${SSH_TARGET}" "$@"
}

ssh_remote_bash() {
  ssh "${SSH_ARGS[@]}" "${SSH_TARGET}" "bash -s"
}

remote_os() {
  if [[ "${VITALAB_REMOTE_OS}" != "auto" ]]; then
    printf '%s\n' "${VITALAB_REMOTE_OS}"
    return
  fi
  local uname_value
  uname_value="$(ssh_remote "uname -s")"
  case "${uname_value}" in
    Linux) printf 'linux\n' ;;
    Darwin) printf 'macos\n' ;;
    *) die "unsupported remote OS: ${uname_value}" ;;
  esac
}

rsync_ssh_cmd() {
  local cmd="ssh -p ${VITALAB_SSH_PORT}"
  if [[ -n "${VITALAB_SSH_CONFIG:-}" ]]; then
    cmd="ssh -F ${VITALAB_SSH_CONFIG} -p ${VITALAB_SSH_PORT}"
  fi
  printf '%s\n' "${cmd}"
}

compose_profile_args() {
  local profiles="${1:-}"
  local result=()
  local item
  profiles="${profiles//,/ }"
  for item in ${profiles}; do
    [[ -n "${item}" ]] || continue
    result+=("--profile" "${item}")
  done
  printf '%s\n' "${result[@]}"
}

shell_quote() {
  printf '%q' "$1"
}
