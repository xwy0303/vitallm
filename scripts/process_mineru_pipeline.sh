#!/usr/bin/env bash
set -euo pipefail

# batch process B1-B5: MinerU artifacts → RAG inputs → evidence → Qdrant index
# MinerU output is at output/<task_id>/B<N>/hybrid_auto/

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

PYTHON=".venv/bin/python3"

# Config
COLLECTION="enzyme_immobilization_b10"
QDRANT_URL="http://127.0.0.1:6333"
EMBEDDING_CONFIG="configs/local.yaml"

for DOC_ID in B1 B2 B3 B4 B5; do
    # Map B number → MinerU task ID (from output/ dirs)
    case "$DOC_ID" in
        B1) TASK_ID="e50bf905-89ac-48fd-bee6-c4d9ce984fbf" ;;
        B2) TASK_ID="76e85245-77ec-4853-8f8b-0ae0b50b6946" ;;
        B3) TASK_ID="9ae77377-4a6a-4807-91ea-735e24fd1320" ;;
        B4) TASK_ID="07df70b7-c701-4d9e-99a9-d55b31cbe597" ;;
        B5) TASK_ID="fbe067c6-4115-43e5-8a6a-b478fce78731" ;;
        *) echo "Unknown doc: $DOC_ID"; exit 1 ;;
    esac
    echo ""
    echo "============================================"
    echo "Processing $DOC_ID (task: ${TASK_ID})"
    echo "============================================"

    ARTIFACT_DIR="output/${TASK_ID}/${DOC_ID}/hybrid_auto"
    RAG_INPUT_DIR="artifacts/rag_inputs/${DOC_ID}"
    EVIDENCE_DIR="artifacts/evidence/${DOC_ID}"

    if [ ! -d "$ARTIFACT_DIR" ]; then
        echo "ERROR: Artifact dir not found: $ARTIFACT_DIR"
        exit 1
    fi

    echo ""
    echo "--- Step 1: Build RAG inputs from MinerU artifacts ---"
    $PYTHON -m scripts.build_rag_inputs \
        --artifact-dir "$ARTIFACT_DIR" \
        --output-dir "$RAG_INPUT_DIR" \
        --document-id "$DOC_ID" \
        --source-pdf "${DOC_ID}.pdf"

    echo ""
    echo "--- Step 2: Extract evidence records ---"
    $PYTHON -m scripts.extract_evidence_records \
        --input-dir "$RAG_INPUT_DIR" \
        --output-dir "$EVIDENCE_DIR"

    echo ""
    echo "--- Step 3: Index into Qdrant ---"
    $PYTHON -m scripts.index_rag_qdrant \
        --rag-input-dir "$RAG_INPUT_DIR" \
        --evidence-dir "$EVIDENCE_DIR" \
        --collection "$COLLECTION" \
        --qdrant-url "$QDRANT_URL" \
        --embedding-config "$EMBEDDING_CONFIG"

    echo ""
    echo "=== Finished $DOC_ID ==="
done

echo ""
echo "============================================"
echo "All done! Checking collection stats..."
echo "============================================"
curl -s "$QDRANT_URL/collections/$COLLECTION" | python3 -c "
import sys, json
d = json.load(sys.stdin).get('result', {})
print(f\"points_count: {d.get('points_count', '?')}\")
print(f\"indexed_vectors_count: {d.get('indexed_vectors_count', '?')}\")
"
