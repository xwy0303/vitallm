#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"
inventory="${1:-${VITALAB_INVENTORY:-}}"
project_name="${2:-shengji-enzyme-rag-lab}"
load_inventory "${inventory}"

kv_namespace_id="${CLOUDFLARE_KV_NAMESPACE_ID:-}"
[[ -n "${kv_namespace_id}" ]] || die "CLOUDFLARE_KV_NAMESPACE_ID is required for KV dynamic origin Pages deploy"

tmp_dir="$(mktemp -d "${TMPDIR:-/tmp}/vitalab-pages.XXXXXX")"
site_dir="${tmp_dir}/site"
cleanup() {
  rm -rf "${tmp_dir}"
}
trap cleanup EXIT

mkdir -p "${site_dir}"
rsync -a "${PROJECT_DIR}/web/" "${site_dir}/"
cp "${DEPLOY_DIR}/cloudflare/pages_worker.template.js" "${site_dir}/_worker.js"
cp "${DEPLOY_DIR}/cloudflare/_redirects.template" "${site_dir}/_redirects"

cat > "${tmp_dir}/wrangler.toml" <<EOF
name = "${project_name}"
pages_build_output_dir = "./site"
compatibility_date = "2026-06-10"

[[kv_namespaces]]
binding = "VITALAB_ORIGIN_KV"
id = "${kv_namespace_id}"

[vars]
CLOUDFLARE_KV_ORIGIN_KEY = "${CLOUDFLARE_KV_ORIGIN_KEY}"
ALLOWED_BACKEND_HOST_SUFFIXES = "${ALLOWED_BACKEND_HOST_SUFFIXES}"
EOF

(
  cd "${tmp_dir}"
  npx wrangler pages deploy ./site --project-name "${project_name}" --commit-dirty=true
)
