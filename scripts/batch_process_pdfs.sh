#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PYTHON="${ROOT_DIR}/.venv/bin/python"

if [[ ! -x "${PYTHON}" ]]; then
  PYTHON="python3"
fi

PDF_DIR="${ROOT_DIR}/MOF固定化脂肪酶文献调研"
ARTIFACT_ROOT="${ROOT_DIR}/artifacts"
CONFIG="${ROOT_DIR}/configs/local.yaml"
UPLOADED_BY="legacy_batch_process_pdfs"
COLLECTION="${INGESTION_COLLECTION:-}"
LIMIT=""
MAX_JOBS=""
MINERU_TIMEOUT_SECONDS="1800"
MINERU_INTERVAL_SECONDS="10"
QDRANT_BATCH_SIZE="64"
REGISTER_ONLY=false
REQUEUE_INDEXED=false
REUSE_MINERU_ARTIFACTS=false
REINDEX_ONLY=false
DELETE_EXISTING_POINTS=false
PDF_NAMES=()

usage() {
  cat <<EOF
Usage: $0 [options] [pdf_names...]

No pdf_names means register and process the full PDF directory.

Options:
  --pdf-dir PATH
  --artifact-root PATH
  --config PATH
  --collection NAME
  --limit N
  --max-jobs N
  --register-only
  --requeue-indexed
  --reuse-mineru-artifacts
  --reindex-only
  --delete-existing-points
  --recreate                  Legacy alias for per-document reindex + delete existing points.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --pdf-dir) PDF_DIR="$2"; shift 2 ;;
    --artifact-root) ARTIFACT_ROOT="$2"; shift 2 ;;
    --config) CONFIG="$2"; shift 2 ;;
    --collection) COLLECTION="$2"; shift 2 ;;
    --limit) LIMIT="$2"; shift 2 ;;
    --max-jobs) MAX_JOBS="$2"; shift 2 ;;
    --mineru-timeout-seconds) MINERU_TIMEOUT_SECONDS="$2"; shift 2 ;;
    --mineru-interval-seconds) MINERU_INTERVAL_SECONDS="$2"; shift 2 ;;
    --qdrant-batch-size) QDRANT_BATCH_SIZE="$2"; shift 2 ;;
    --register-only) REGISTER_ONLY=true; shift ;;
    --requeue-indexed) REQUEUE_INDEXED=true; shift ;;
    --reuse-mineru-artifacts) REUSE_MINERU_ARTIFACTS=true; shift ;;
    --reindex-only) REINDEX_ONLY=true; shift ;;
    --delete-existing-points) DELETE_EXISTING_POINTS=true; shift ;;
    --recreate)
      REQUEUE_INDEXED=true
      REINDEX_ONLY=true
      DELETE_EXISTING_POINTS=true
      shift
      ;;
    -h|--help) usage; exit 0 ;;
    --) shift; PDF_NAMES+=("$@"); break ;;
    -*) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
    *) PDF_NAMES+=("$1"); shift ;;
  esac
done

export PYTHONPATH="${ROOT_DIR}/src${PYTHONPATH:+:${PYTHONPATH}}"

register_cmd=(
  "${PYTHON}" "${SCRIPT_DIR}/register_pdf_corpus.py"
  --pdf-dir "${PDF_DIR}"
  --artifact-root "${ARTIFACT_ROOT}"
  --uploaded-by "${UPLOADED_BY}"
  --queue-jobs
)

if [[ -n "${LIMIT}" ]]; then
  register_cmd+=(--limit "${LIMIT}")
fi
for pdf_name in "${PDF_NAMES[@]}"; do
  register_cmd+=(--pdf-name "${pdf_name}")
done
if [[ "${REQUEUE_INDEXED}" == true || "${REINDEX_ONLY}" == true || "${DELETE_EXISTING_POINTS}" == true ]]; then
  register_cmd+=(--requeue-indexed)
fi
if [[ -n "${COLLECTION}" ]]; then
  register_cmd+=(--target-collection "${COLLECTION}")
fi

printf '+'
printf ' %q' "${register_cmd[@]}"
printf '\n'
register_output="$("${register_cmd[@]}" 2>&1)"
printf '%s\n' "${register_output}"

if [[ "${REGISTER_ONLY}" == true ]]; then
  exit 0
fi

worker_base=(
  "${PYTHON}" "${SCRIPT_DIR}/run_ingestion_worker.py"
  --config "${CONFIG}"
  --artifact-root "${ARTIFACT_ROOT}"
  --mineru-timeout-seconds "${MINERU_TIMEOUT_SECONDS}"
  --mineru-interval-seconds "${MINERU_INTERVAL_SECONDS}"
  --qdrant-batch-size "${QDRANT_BATCH_SIZE}"
)

if [[ -n "${COLLECTION}" ]]; then
  worker_base+=(--collection "${COLLECTION}")
fi
if [[ -n "${MAX_JOBS}" ]]; then
  worker_base+=(--max-jobs "${MAX_JOBS}")
fi
if [[ "${REUSE_MINERU_ARTIFACTS}" == true ]]; then
  worker_base+=(--reuse-mineru-artifacts)
fi
if [[ "${REINDEX_ONLY}" == true ]]; then
  worker_base+=(--reindex-only)
fi
if [[ "${DELETE_EXISTING_POINTS}" == true ]]; then
  worker_base+=(--delete-existing-points)
fi

if [[ ${#PDF_NAMES[@]} -gt 0 ]]; then
  document_ids="$(printf '%s\n' "${register_output}" | sed -n 's/^document_ids=//p' | tail -1)"
  if [[ -z "${document_ids}" ]]; then
    echo "register_pdf_corpus.py did not report document_ids" >&2
    exit 2
  fi
  IFS=',' read -r -a ids <<< "${document_ids}"
  for document_id in "${ids[@]}"; do
    [[ -z "${document_id}" ]] && continue
    cmd=("${worker_base[@]}" --document-id "${document_id}")
    printf '+'
    printf ' %q' "${cmd[@]}"
    printf '\n'
    "${cmd[@]}"
  done
else
  cmd=("${worker_base[@]}" --until-empty)
  printf '+'
  printf ' %q' "${cmd[@]}"
  printf '\n'
  "${cmd[@]}"
fi
