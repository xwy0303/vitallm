#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

MINERU_URL="http://127.0.0.1:8000"
RAG_EVIDENCE_ROOT="${ROOT_DIR}/artifacts"
QDRANT_URL="http://127.0.0.1:6333"
COLLECTION="enzyme_immobilization_b10"
PYTHON="${ROOT_DIR}/.venv/bin/python"

RECREATE=false
BATCH=()
PDF_DIR="${ROOT_DIR}/MOF固定化脂肪酶文献调研"

usage() {
    echo "Usage: $0 [--recreate] [--collection NAME] pdf_names..."
    echo "  pdf_names: e.g. B1 B2 B3 (without .pdf extension)"
    echo "  --recreate: drop and recreate the Qdrant collection before indexing"
    echo "  --collection NAME: target Qdrant collection name"
    exit 1
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --recreate) RECREATE=true; shift ;;
        --collection) COLLECTION="$2"; shift 2 ;;
        -h|--help) usage ;;
        *) BATCH+=("$1"); shift ;;
    esac
done

if [[ ${#BATCH[@]} -eq 0 ]]; then
    echo "Error: specify at least one PDF name (e.g. B1 B2 B3)"
    usage
fi

RECREATE_FLAG=""
if $RECREATE; then
    RECREATE_FLAG="--recreate"
fi

PYTHONPATH="${ROOT_DIR}/src"
export PYTHONPATH
export HTTPS_PROXY="${HTTPS_PROXY:-http://127.0.0.1:7890}"

for PDF_NAME in "${BATCH[@]}"; do
    PDF_PATH="${PDF_DIR}/${PDF_NAME}.pdf"
    echo ""
    echo "========================================"
    echo "Processing: ${PDF_NAME}"
    echo "========================================"

    if [[ ! -f "${PDF_PATH}" ]]; then
        echo "WARNING: ${PDF_PATH} not found, skipping."
        continue
    fi

    # Step 1: Submit to MinerU and wait for result
    echo "[Step 1/4] Submitting ${PDF_NAME} to MinerU..."
    MINERU_OUTPUT=$("${PYTHON}" "${SCRIPT_DIR}/run_mineru_smoke.py" \
        --pdf "${PDF_PATH}" \
        --submit-base-url "${MINERU_URL}" \
        --result-base-url "${MINERU_URL}" \
        --artifact-root "${RAG_EVIDENCE_ROOT}/mineru_local_smoke" \
        --lang-list en \
        --timeout-seconds 1800 \
        --interval-seconds 10 2>&1)
    echo "${MINERU_OUTPUT}"

    # Extract task_id and artifact_dir from output
    TASK_ID=$(echo "${MINERU_OUTPUT}" | grep -o '"task_id": *"[^"]*"' | head -1 | cut -d'"' -f4)
    ARTIFACT_DIR=$(echo "${MINERU_OUTPUT}" | grep -o '"artifact_dir": *"[^"]*"' | head -1 | cut -d'"' -f4)
    SUBMIT_STATUS=$(echo "${MINERU_OUTPUT}" | grep -o '"status": *"[^"]*"' | head -1 | cut -d'"' -f4)

    if [[ "${SUBMIT_STATUS}" == "submit_failed" ]]; then
        echo "ERROR: MinerU submission failed for ${PDF_NAME}, skipping."
        continue
    fi

    if [[ -z "${ARTIFACT_DIR}" ]]; then
        echo "WARNING: Could not determine artifact_dir for ${PDF_NAME}, looking for auto-created directory..."
        # Look for the most recent artifact directory containing this PDF name
        ARTIFACT_DIR=$(ls -td "${RAG_EVIDENCE_ROOT}/mineru_local_smoke/${PDF_NAME}"_* 2>/dev/null | head -1) || true
        if [[ -z "${ARTIFACT_DIR}" ]]; then
            echo "ERROR: Cannot find MinerU artifact for ${PDF_NAME}, skipping."
            continue
        fi
    fi

    echo "Task ID: ${TASK_ID}"
    echo "Artifact: ${ARTIFACT_DIR}"

    # Step 2: Build RAG inputs
    echo "[Step 2/4] Building RAG inputs..."
    RAG_INPUT_DIR="${RAG_EVIDENCE_ROOT}/rag_inputs/${PDF_NAME}"
    "${PYTHON}" "${SCRIPT_DIR}/build_rag_inputs.py" \
        --artifact-dir "${ARTIFACT_DIR}" \
        --output-dir "${RAG_INPUT_DIR}" \
        --document-id "${PDF_NAME}" \
        --source-pdf "${PDF_NAME}.pdf" 2>&1

    # Step 3: Extract evidence
    echo "[Step 3/4] Extracting evidence..."
    EVIDENCE_DIR="${RAG_EVIDENCE_ROOT}/evidence/${PDF_NAME}"
    "${PYTHON}" "${SCRIPT_DIR}/extract_evidence_records.py" \
        --input-dir "${RAG_INPUT_DIR}" \
        --output-dir "${EVIDENCE_DIR}" 2>&1

    echo "Completed ${PDF_NAME}: RAG inputs → evidence extracted"

done

# Step 4: Index each processed paper into Qdrant
echo ""
echo "========================================"
echo "Final Step: Indexing new papers into Qdrant"
echo "Collection: ${COLLECTION}"
echo "========================================"

for PDF_NAME in "${BATCH[@]}"; do
    RAG_DIR="${RAG_EVIDENCE_ROOT}/rag_inputs/${PDF_NAME}"
    EVI_DIR="${RAG_EVIDENCE_ROOT}/evidence/${PDF_NAME}"
    if [[ ! -d "${RAG_DIR}" ]] || [[ ! -d "${EVI_DIR}" ]]; then
        echo "Skipping ${PDF_NAME}: missing RAG inputs or evidence"
        continue
    fi
    echo "Indexing ${PDF_NAME} into ${COLLECTION}..."
    "${PYTHON}" "${SCRIPT_DIR}/index_rag_qdrant.py" \
        --rag-input-dir "${RAG_DIR}" \
        --evidence-dir "${EVI_DIR}" \
        --collection "${COLLECTION}" \
        --qdrant-url "${QDRANT_URL}" \
        --embedding-config "${ROOT_DIR}/configs/local.yaml" \
        ${RECREATE_FLAG} 2>&1
    # Only recreate on first paper
    RECREATE_FLAG=""
done

echo ""
echo "========================================"
echo "Batch processing complete!"
echo "Papers: ${BATCH[*]}"
echo "Collection: ${COLLECTION}"
echo "========================================"
