#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/bin/common.sh"
load_local_env

AGENT_DIR="${HOME}/Library/LaunchAgents"
APP_ROOT="${HOME}/Library/Application Support/Shengji/app"
WRAPPER_DIR="${HOME}/Library/Application Support/Shengji/bin"
UID_VALUE="$(id -u)"
PROJECT_DIR="${PROJECT_DIR}"
LOG_DIR="${LOG_DIR}"

labels=(
  com.shengji.qdrant
  com.shengji.mineru
  com.shengji.api
  com.shengji.ingestion-worker
  com.shengji.web
  com.shengji.logrotate
)

sed_escape() {
  printf '%s' "$1" | sed -e 's/[\/&]/\\&/g'
}

render_template() {
  local template="$1"
  local output="$2"
  local escaped_project_dir escaped_log_dir escaped_wrapper_dir
  escaped_project_dir="$(sed_escape "${PROJECT_DIR}")"
  escaped_log_dir="$(sed_escape "${LOG_DIR}")"
  escaped_wrapper_dir="$(sed_escape "${WRAPPER_DIR}")"
  sed \
    -e "s/__PROJECT_DIR__/${escaped_project_dir}/g" \
    -e "s/__LOG_DIR__/${escaped_log_dir}/g" \
    -e "s/__WRAPPER_DIR__/${escaped_wrapper_dir}/g" \
    "${template}" > "${output}"
}

bootout_if_loaded() {
  local label="$1"
  launchctl bootout "gui/${UID_VALUE}" "${AGENT_DIR}/${label}.plist" >/dev/null 2>&1 || true
}

sync_runtime_path() {
  local path="$1"
  local source="${PROJECT_DIR}/${path}"
  local target="${APP_ROOT}/${path}"
  if [[ ! -e "${source}" ]]; then
    return
  fi
  mkdir -p "$(dirname "${target}")"
  ditto "${source}" "${target}"
}

mkdir -p "${AGENT_DIR}" "${LOG_DIR}"
mkdir -p "${APP_ROOT}" "${WRAPPER_DIR}"

for label in "${labels[@]}"; do
  bootout_if_loaded "${label}"
done

"${SCRIPT_DIR}/bin/check_ports.sh"

for path in src web configs schemas scripts .local .venv .venv-mineru "MOF固定化脂肪酶文献调研"; do
  sync_runtime_path "${path}"
done

if [[ ! -d "${APP_ROOT}/artifacts" ]]; then
  sync_runtime_path artifacts
fi

mkdir -p "${APP_ROOT}/deploy/local"
if [[ -f "${PROJECT_DIR}/deploy/local/env.local" ]]; then
  install -m 600 "${PROJECT_DIR}/deploy/local/env.local" "${APP_ROOT}/deploy/local/env.local"
fi
if [[ -f "${PROJECT_DIR}/.env.local" ]]; then
  install -m 600 "${PROJECT_DIR}/.env.local" "${APP_ROOT}/.env.local"
fi

cat > "${WRAPPER_DIR}/run_qdrant.sh" <<EOF
#!/usr/bin/env bash
set -euo pipefail

APP_ROOT="${APP_ROOT}"
cd "\${APP_ROOT}"
if [[ -f deploy/local/env.local ]]; then
  set -a
  source deploy/local/env.local
  set +a
fi

QDRANT_BIN="\${APP_ROOT}/.local/qdrant/qdrant"
QDRANT_STORAGE="\${APP_ROOT}/.local/qdrant/storage"
QDRANT_HTTP_PORT="\${QDRANT_HTTP_PORT:-6333}"
QDRANT_GRPC_PORT="\${QDRANT_GRPC_PORT:-6334}"

if [[ ! -x "\${QDRANT_BIN}" ]]; then
  echo "Qdrant binary not found or not executable: \${QDRANT_BIN}" >&2
  exit 1
fi

mkdir -p "\${QDRANT_STORAGE}"
exec env \\
  QDRANT__STORAGE__STORAGE_PATH="\${QDRANT_STORAGE}" \\
  QDRANT__SERVICE__HTTP_PORT="\${QDRANT_HTTP_PORT}" \\
  QDRANT__SERVICE__GRPC_PORT="\${QDRANT_GRPC_PORT}" \\
  "\${QDRANT_BIN}" --disable-telemetry
EOF

cat > "${WRAPPER_DIR}/run_mineru.sh" <<EOF
#!/usr/bin/env bash
set -euo pipefail

APP_ROOT="${APP_ROOT}"
cd "\${APP_ROOT}"
if [[ -f deploy/local/env.local ]]; then
  set -a
  source deploy/local/env.local
  set +a
fi

MINERU_PYTHON="\${APP_ROOT}/.venv-mineru/bin/python"
MINERU_HOST="\${MINERU_HOST:-127.0.0.1}"
MINERU_PORT="\${MINERU_PORT:-8000}"
MINERU_ENABLE_VLM_PRELOAD="\${MINERU_ENABLE_VLM_PRELOAD:-false}"

if [[ ! -x "\${MINERU_PYTHON}" ]]; then
  echo "MinerU Python runtime not found or not executable: \${MINERU_PYTHON}" >&2
  exit 1
fi

exec "\${MINERU_PYTHON}" -c 'from mineru.cli.fast_api import main; raise SystemExit(main())' \\
  --host "\${MINERU_HOST}" \\
  --port "\${MINERU_PORT}" \\
  --enable-vlm-preload "\${MINERU_ENABLE_VLM_PRELOAD}"
EOF

cat > "${WRAPPER_DIR}/run_api.sh" <<EOF
#!/usr/bin/env bash
set -euo pipefail

APP_ROOT="${APP_ROOT}"
cd "\${APP_ROOT}"
if [[ -f deploy/local/env.local ]]; then
  set -a
  source deploy/local/env.local
  set +a
fi
if [[ -f .env.local ]]; then
  set -a
  source .env.local
  set +a
fi

QDRANT_HTTP_PORT="\${QDRANT_HTTP_PORT:-6333}"
ENZYME_API_HOST="\${ENZYME_API_HOST:-127.0.0.1}"
ENZYME_API_PORT="\${ENZYME_API_PORT:-8001}"
ENZYME_RUNTIME_CONFIG="\${ENZYME_RUNTIME_CONFIG:-configs/local.yaml}"
started_at="\$(date +%s)"

until curl -fsS "http://127.0.0.1:\${QDRANT_HTTP_PORT}/collections" >/dev/null 2>&1; do
  if (( "\$(date +%s)" - started_at >= 60 )); then
    echo "Timed out waiting for Qdrant on port \${QDRANT_HTTP_PORT}" >&2
    exit 1
  fi
  sleep 1
done

exec env \\
  PYTHONPATH=src \\
  ENZYME_API_HOST="\${ENZYME_API_HOST}" \\
  ENZYME_API_PORT="\${ENZYME_API_PORT}" \\
  ENZYME_RUNTIME_CONFIG="\${ENZYME_RUNTIME_CONFIG}" \\
  .venv/bin/python -m uvicorn enzyme_recommender.api.app:app \\
    --host "\${ENZYME_API_HOST}" \\
    --port "\${ENZYME_API_PORT}" \\
    --app-dir .
EOF

cat > "${WRAPPER_DIR}/run_web.sh" <<EOF
#!/usr/bin/env bash
set -euo pipefail

APP_ROOT="${APP_ROOT}"
cd "\${APP_ROOT}"
if [[ -f deploy/local/env.local ]]; then
  set -a
  source deploy/local/env.local
  set +a
fi

WEB_HOST="\${SHENGJI_WEB_HOST:-127.0.0.1}"
WEB_PORT="\${SHENGJI_WEB_PORT:-5173}"
PYTHON_BIN="\${SHENGJI_PYTHON_BIN:-/usr/bin/python3}"

if [[ ! -x "\${PYTHON_BIN}" ]]; then
  echo "python3 executable not found. Set SHENGJI_PYTHON_BIN in deploy/local/env.local." >&2
  exit 1
fi

exec "\${PYTHON_BIN}" - <<PY
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer


class NoCacheHandler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()


server = ThreadingHTTPServer(
    ("\${WEB_HOST}", int("\${WEB_PORT}")),
    partial(NoCacheHandler, directory="web"),
)
server.serve_forever()
PY
EOF

cat > "${WRAPPER_DIR}/run_ingestion_worker.sh" <<EOF
#!/usr/bin/env bash
set -euo pipefail

APP_ROOT="${APP_ROOT}"
cd "\${APP_ROOT}"
if [[ -f deploy/local/env.local ]]; then
  set -a
  source deploy/local/env.local
  set +a
fi
if [[ -f .env.local ]]; then
  set -a
  source .env.local
  set +a
fi

QDRANT_HTTP_PORT="\${QDRANT_HTTP_PORT:-6333}"
MINERU_PORT="\${MINERU_PORT:-8000}"
ENZYME_RUNTIME_CONFIG="\${ENZYME_RUNTIME_CONFIG:-configs/local.yaml}"
INGESTION_POLL_SECONDS="\${INGESTION_POLL_SECONDS:-10}"
INGESTION_MINERU_TIMEOUT_SECONDS="\${INGESTION_MINERU_TIMEOUT_SECONDS:-1800}"
INGESTION_MINERU_INTERVAL_SECONDS="\${INGESTION_MINERU_INTERVAL_SECONDS:-10}"
INGESTION_QDRANT_BATCH_SIZE="\${INGESTION_QDRANT_BATCH_SIZE:-64}"
INGESTION_COLLECTION="\${INGESTION_COLLECTION:-}"
started_at="\$(date +%s)"

until curl -fsS "http://127.0.0.1:\${QDRANT_HTTP_PORT}/collections" >/dev/null 2>&1; do
  if (( "\$(date +%s)" - started_at >= 60 )); then
    echo "Timed out waiting for Qdrant on port \${QDRANT_HTTP_PORT}" >&2
    exit 1
  fi
  sleep 1
done

started_at="\$(date +%s)"
until curl -fsS "http://127.0.0.1:\${MINERU_PORT}/docs" >/dev/null 2>&1 || curl -fsS "http://127.0.0.1:\${MINERU_PORT}/openapi.json" >/dev/null 2>&1; do
  if (( "\$(date +%s)" - started_at >= 120 )); then
    echo "Timed out waiting for MinerU on port \${MINERU_PORT}" >&2
    exit 1
  fi
  sleep 2
done

run_worker() {
  exec env \\
    PYTHONPATH=src \\
    ENZYME_RUNTIME_CONFIG="\${ENZYME_RUNTIME_CONFIG}" \\
    .venv/bin/python scripts/run_ingestion_worker.py \\
      --config "\${ENZYME_RUNTIME_CONFIG}" \\
      --artifact-root artifacts \\
      --poll-seconds "\${INGESTION_POLL_SECONDS}" \\
      --mineru-timeout-seconds "\${INGESTION_MINERU_TIMEOUT_SECONDS}" \\
      --mineru-interval-seconds "\${INGESTION_MINERU_INTERVAL_SECONDS}" \\
      --qdrant-batch-size "\${INGESTION_QDRANT_BATCH_SIZE}" \\
      "\$@"
}

if [[ -n "\${INGESTION_COLLECTION}" ]]; then
  run_worker --collection "\${INGESTION_COLLECTION}"
else
  run_worker
fi
EOF

cat > "${WRAPPER_DIR}/rotate_logs.sh" <<EOF
#!/usr/bin/env bash
set -euo pipefail

APP_ROOT="${APP_ROOT}"
LOG_DIR="${LOG_DIR}"
cd "\${APP_ROOT}"
if [[ -f deploy/local/env.local ]]; then
  set -a
  source deploy/local/env.local
  set +a
fi

LOG_DIR="\${SHENGJI_LOG_DIR:-\${LOG_DIR}}"
max_bytes="\${SHENGJI_LOG_MAX_BYTES:-52428800}"
retention_days="\${SHENGJI_LOG_RETENTION_DAYS:-14}"
timestamp="\$(date +%Y%m%d-%H%M%S)"

mkdir -p "\${LOG_DIR}"
for file in "\${LOG_DIR}"/*.log; do
  [[ -f "\${file}" ]] || continue
  size="\$(stat -f '%z' "\${file}")"
  if (( size >= max_bytes )); then
    rotated="\${file}.\${timestamp}"
    cp "\${file}" "\${rotated}"
    gzip -f "\${rotated}"
    : > "\${file}"
  fi
done

find "\${LOG_DIR}" -name '*.gz' -type f -mtime +"\${retention_days}" -delete
EOF

chmod 755 "${WRAPPER_DIR}"/*.sh

for label in "${labels[@]}"; do
  template="${SCRIPT_DIR}/launchd/${label}.plist.template"
  output="${AGENT_DIR}/${label}.plist"
  if [[ ! -f "${template}" ]]; then
    echo "Missing template: ${template}" >&2
    exit 1
  fi
  render_template "${template}" "${output}"
  plutil -lint "${output}" >/dev/null
done

for label in "${labels[@]}"; do
  launchctl bootstrap "gui/${UID_VALUE}" "${AGENT_DIR}/${label}.plist"
done

echo "Installed Shengji LaunchAgents:"
for label in "${labels[@]}"; do
  echo "  ${label}"
done
echo "Logs: ${LOG_DIR}"
