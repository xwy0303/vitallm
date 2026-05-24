#!/usr/bin/env bash
set -euo pipefail

# Batch process all PDFs through MinerU in small groups, then do RAG/evidence/indexing

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

PYTHON=".venv/bin/python"
PDF_DIR="MOF固定化脂肪酶文献调研"
RAG_DIR="artifacts/rag_inputs"
EVI_DIR="artifacts/evidence"
MINERU_URL="http://127.0.0.1:8000"
QDRANT_URL="http://127.0.0.1:6333"
COLLECTION="enzyme_immobilization_b10"
CONFIG="configs/local.yaml"

# Get all PDFs that haven't been fully processed (no rag_chunks.jsonl)
BATCH_SIZE=8

to_process=()
for pdf in "$PDF_DIR"/*.pdf; do
    name=$(basename "$pdf" .pdf)
    # Strip trailing space from filename
    cleaned=$(echo "$name" | sed 's/[[:space:]]*$//')
    if [ ! -f "$RAG_DIR/$cleaned/rag_chunks.jsonl" ]; then
        to_process+=("$cleaned")
    fi
done

echo "PDFs to process: ${#to_process[@]}"
echo ""

# If there's a C6 with trailing space, create a symlink without the space
if [ -f "$PDF_DIR/C6 .pdf" ] && [ ! -f "$PDF_DIR/C6.pdf" ]; then
    ln -sf "C6 .pdf" "$PDF_DIR/C6.pdf"
fi

total_batches=$(( (${#to_process[@]} + BATCH_SIZE - 1) / BATCH_SIZE ))
batch_num=0
all_processed=()

for ((i=0; i<${#to_process[@]}; i+=BATCH_SIZE)); do
    batch=("${to_process[@]:i:BATCH_SIZE}")
    batch_num=$((batch_num + 1))
    echo ""
    echo "============================================"
    echo "Batch $batch_num / $total_batches: ${batch[*]}"
    echo "============================================"

    # Build PDF paths for this batch
    pdf_args=()
    for name in "${batch[@]}"; do
        # Handle C6 space issue
        if [ "$name" = "C6" ] && [ -f "$PDF_DIR/C6 .pdf" ]; then
            pdf_args+=("$PDF_DIR/C6 .pdf")
        else
            pdf_args+=("$PDF_DIR/$name.pdf")
        fi
    done

    # Submit batch to MinerU
    echo "Submitting to MinerU..."
    task_output=$(
        $PYTHON -c "
import sys, json
from pathlib import Path
sys.path.insert(0, 'src')
from enzyme_recommender.ingestion import MinerUClient, MinerUOptions

options = MinerUOptions(
    return_model_output='false',
    return_middle_json='true',
    response_format_zip='true',
)
client = MinerUClient(submit_base_url='$MINERU_URL', result_base_url='$MINERU_URL', timeout=180.0)
task_id, payload = client.submit_pdfs(
    [Path(p) for p in sys.argv[1:]],
    options
)
print(task_id)
print(json.dumps(payload, ensure_ascii=False))
" "${pdf_args[@]}" 2>&1
    ) || {
        echo "MinerU submission failed for batch $batch_num, will retry individually"
        for name in "${batch[@]}"; do
            echo "  Retrying $name individually..."
            pdf_path="$PDF_DIR/$name.pdf"
            [ "$name" = "C6" ] && [ -f "$PDF_DIR/C6 .pdf" ] && pdf_path="$PDF_DIR/C6 .pdf"
            task_output=$(
                $PYTHON -c "
import sys, json
from pathlib import Path
sys.path.insert(0, 'src')
from enzyme_recommender.ingestion import MinerUClient, MinerUOptions
options = MinerUOptions(return_model_output='false', return_middle_json='true', response_format_zip='true')
client = MinerUClient(submit_base_url='$MINERU_URL', result_base_url='$MINERU_URL', timeout=180.0)
task_id, payload = client.submit_pdfs([Path('$pdf_path')], options)
print(task_id)
print(json.dumps(payload, ensure_ascii=False))
" 2>&1
            ) || { echo "  FAILED $name, skipping"; continue; }
            task_id=$(echo "$task_output" | head -1)
            echo "  Task $task_id submitted for $name, polling..."
            $PYTHON -c "
import sys, json
from pathlib import Path
sys.path.insert(0, 'src')
from enzyme_recommender.ingestion import MinerUClient
client = MinerUClient(submit_base_url='$MINERU_URL', result_base_url='$MINERU_URL', timeout=180.0)
result = client.poll_until_done('$task_id', timeout_seconds=1800, interval_seconds=15)
print(result.status)
" 2>&1 && echo "  $name completed" || echo "  $name FAILED"
        done
        continue
    }

    task_id=$(echo "$task_output" | head -1)
    echo "Task ID: $task_id"

    # Poll for completion
    echo "Waiting for MinerU batch to complete (this may take a while)..."
    if $PYTHON -c "
import sys
sys.path.insert(0, 'src')
from enzyme_recommender.ingestion import MinerUClient
client = MinerUClient(submit_base_url='$MINERU_URL', result_base_url='$MINERU_URL', timeout=180.0)
result = client.poll_until_done('$task_id', timeout_seconds=3600, interval_seconds=15)
print('Result status:', result.status)
" 2>&1; then
        echo "Batch $batch_num completed successfully"
        all_processed+=("${batch[@]}")
    else
        echo "Batch $batch_num MinerU processing failed, continuing to next batch"
    fi
done

echo ""
echo "========================================"
echo "MinerU processing complete. Now processing RAG inputs + evidence + indexing..."
echo "========================================"

# Now scan output/ for ALL MinerU results and do the downstream pipeline
$PYTHON -c "
import sys
from pathlib import Path
sys.path.insert(0, 'src')

PROJECT_DIR = Path('.')
OUTPUT_DIR = PROJECT_DIR / 'output'
RAG_INPUTS_DIR = PROJECT_DIR / 'artifacts/rag_inputs'
EVIDENCE_DIR = PROJECT_DIR / 'artifacts/evidence'

# Find all MinerU output dirs
doc_map = {}
if OUTPUT_DIR.exists():
    for task_dir in OUTPUT_DIR.iterdir():
        if not task_dir.is_dir() or task_dir.name == 'pdf':
            continue
        for doc_dir in task_dir.iterdir():
            if not doc_dir.is_dir():
                continue
            for method_dir in ['hybrid_auto', 'auto']:
                candidate = doc_dir / method_dir
                if candidate.is_dir() and list(candidate.glob('*_content_list.json')):
                    doc_map[doc_dir.name.strip()] = candidate
                    break

print(f'Found {len(doc_map)} MinerU outputs')
for doc_id, path in sorted(doc_map.items()):
    print(f'  {doc_id}: {path}')
" 2>&1

echo ""
echo "=== Building RAG inputs ==="
$PYTHON -c "
import sys
from pathlib import Path
sys.path.insert(0, 'src')
from enzyme_recommender.rag import build_rag_inputs
from enzyme_recommender.rag.artifacts import write_json, write_jsonl

PROJECT_DIR = Path('.')
OUTPUT_DIR = PROJECT_DIR / 'output'
RAG_DIR = PROJECT_DIR / 'artifacts/rag_inputs'

doc_map = {}
for task_dir in OUTPUT_DIR.iterdir():
    if not task_dir.is_dir() or task_dir.name == 'pdf': continue
    for doc_dir in task_dir.iterdir():
        if not doc_dir.is_dir(): continue
        for m in ['hybrid_auto', 'auto']:
            c = doc_dir / m
            if c.is_dir() and list(c.glob('*_content_list.json')):
                doc_map[doc_dir.name.strip()] = c

for doc_id, artifact_dir in sorted(doc_map.items()):
    rag_out = RAG_DIR / doc_id
    if rag_out.exists() and (rag_out / 'rag_chunks.jsonl').exists():
        print(f'  SKIP {doc_id}: already has RAG inputs')
        continue
    try:
        outputs = build_rag_inputs(artifact_dir=artifact_dir, source_pdf=f'{doc_id}.pdf', document_id=doc_id)
        rag_out.mkdir(parents=True, exist_ok=True)
        write_json(rag_out / 'document_manifest.json', outputs['manifest'])
        write_jsonl(rag_out / 'rag_chunks.jsonl', outputs['rag_chunks'])
        write_jsonl(rag_out / 'table_records.jsonl', outputs['table_records'])
        write_jsonl(rag_out / 'extraction_candidates.jsonl', outputs['extraction_candidates'])
        c = outputs['manifest']['counts']
        print(f'  OK {doc_id}: chunks={c[\"rag_chunks\"]} tables={c[\"table_records\"]} candidates={c[\"extraction_candidates\"]} pages={c[\"pages\"]}')
    except Exception as e:
        print(f'  FAIL {doc_id}: {e}')
" 2>&1

echo ""
echo "=== Extracting evidence records ==="
$PYTHON -c "
import sys
from pathlib import Path
sys.path.insert(0, 'src')
from enzyme_recommender.evidence import extract_evidence_records
from enzyme_recommender.rag.artifacts import write_json, write_jsonl

RAG_DIR = Path('artifacts/rag_inputs')
EVI_DIR = Path('artifacts/evidence')

for doc_dir in sorted(RAG_DIR.iterdir()):
    if not doc_dir.is_dir(): continue
    doc_id = doc_dir.name
    if not (doc_dir / 'rag_chunks.jsonl').exists(): continue
    ev_out = EVI_DIR / doc_id
    if ev_out.exists() and (ev_out / 'evidence_records.jsonl').exists():
        print(f'  SKIP {doc_id}: already has evidence')
        continue
    try:
        outputs = extract_evidence_records(doc_dir)
        ev_out.mkdir(parents=True, exist_ok=True)
        write_jsonl(ev_out / 'evidence_records.jsonl', outputs['evidence_records'])
        write_jsonl(ev_out / 'review_queue.jsonl', outputs['review_queue'])
        write_json(ev_out / 'validation_report.json', outputs['validation_report'])
        r = outputs['validation_report']
        print(f'  OK {doc_id}: evidence={r[\"output_counts\"][\"evidence_records\"]} review={r[\"output_counts\"][\"review_queue\"]}')
    except Exception as e:
        print(f'  FAIL {doc_id}: {e}')
" 2>&1

echo ""
echo "=== Indexing to Qdrant ==="
$PYTHON -c "
import sys
from pathlib import Path
from collections import Counter
sys.path.insert(0, 'src')
from enzyme_recommender.rag.embedding import SentenceEmbeddingConfig, SentenceEmbeddingModel
from enzyme_recommender.rag.qdrant import QdrantConfig, QdrantRestClient, build_index_points
from enzyme_recommender.runtime.config import RuntimeConfig

config = RuntimeConfig.from_file(Path('$CONFIG'))
emb = config.embedding
if emb.provider == 'sentence':
    model = SentenceEmbeddingModel(SentenceEmbeddingConfig(
        model_name=emb.model_name,
        dimensions=emb.dimensions,
        device=emb.device,
        cache_folder=emb.cache_folder,
        local_files_only=emb.local_files_only,
    ))
else:
    from enzyme_recommender.rag.embedding import HashEmbeddingConfig, HashEmbeddingModel
    model = HashEmbeddingModel(HashEmbeddingConfig(dimensions=emb.dimensions))

RAG_DIR = Path('artifacts/rag_inputs')
EVI_DIR = Path('artifacts/evidence')

all_points = []
for doc_dir in sorted(RAG_DIR.iterdir()):
    if not doc_dir.is_dir(): continue
    doc_id = doc_dir.name
    if not (doc_dir / 'rag_chunks.jsonl').exists(): continue
    ev_dir = EVI_DIR / doc_id
    ev_arg = ev_dir if ev_dir.exists() else None
    try:
        pts = build_index_points(rag_input_dir=doc_dir, evidence_dir=ev_arg, embedding_model=model)
        all_points.extend(pts)
        print(f'  {doc_id}: {len(pts)} points')
    except Exception as e:
        print(f'  FAIL {doc_id}: {e}')

print(f'\\nTotal: {len(all_points)} points')
counts = Counter(p['payload']['point_type'] for p in all_points)
print(f'By type: {dict(counts)}')

qdrant_config = QdrantConfig(url='$QDRANT_URL', collection='$COLLECTION')
with QdrantRestClient(qdrant_config) as client:
    client.ensure_collection(vector_size=model.dimensions, recreate=False)
    client.upsert_points(all_points, batch_size=64)

print(f'Indexed to {qdrant_config.collection}')
" 2>&1

echo ""
echo "========================================"
echo "ALL DONE! Final collection stats:"
echo "========================================"
curl -s "$QDRANT_URL/collections/$COLLECTION" | python3 -c "
import sys, json
d = json.load(sys.stdin).get('result', {})
print(f'points_count: {d.get(\"points_count\", \"?\")}')
print(f'status: {d.get(\"status\", \"?\")}')
"
