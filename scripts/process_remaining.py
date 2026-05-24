#!/usr/bin/env python3
"""
Continue batch processing from where we left off:
  1. Build RAG inputs + evidence for ALL MinerU results in output/ that have content_list
  2. Submit remaining PDFs to MinerU one by one, process each immediately
  3. Finally index everything to Qdrant
"""

from __future__ import annotations

import json
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Optional

import httpx

from enzyme_recommender.evidence import extract_evidence_records
from enzyme_recommender.ingestion import MinerUClient, MinerUOptions
from enzyme_recommender.rag import build_rag_inputs
from enzyme_recommender.rag.artifacts import write_json, write_jsonl
from enzyme_recommender.rag.embedding import SentenceEmbeddingConfig, SentenceEmbeddingModel
from enzyme_recommender.rag.qdrant import QdrantConfig, QdrantRestClient, build_index_points
from enzyme_recommender.runtime.config import RuntimeConfig

PROJECT_DIR = Path(__file__).resolve().parent.parent
PDF_DIR = PROJECT_DIR / "MOF固定化脂肪酶文献调研"
OUTPUT_DIR = PROJECT_DIR / "output"
RAG_DIR = PROJECT_DIR / "artifacts" / "rag_inputs"
EVI_DIR = PROJECT_DIR / "artifacts" / "evidence"
CONFIG_PATH = PROJECT_DIR / "configs" / "local.yaml"
MINERU_URL = "http://127.0.0.1:8000"
QDRANT_URL = "http://127.0.0.1:6333"
COLLECTION = "enzyme_immobilization_b10"


def normalize_doc_id(value: str) -> str:
    return value.strip()


def find_existing_mineru_results() -> dict[str, Path]:
    """Return {doc_id: artifact_dir} for all successful MinerU parses in output/."""
    results: dict[str, Path] = {}
    if not OUTPUT_DIR.exists():
        return results
    for task_dir in OUTPUT_DIR.iterdir():
        if not task_dir.is_dir() or task_dir.name == "pdf":
            continue
        for doc_dir in task_dir.iterdir():
            if not doc_dir.is_dir() or doc_dir.name == "uploads":
                continue
            doc_id = normalize_doc_id(doc_dir.name)
            for method in ["hybrid_auto", "auto"]:
                candidate = doc_dir / method
                if candidate.is_dir() and list(candidate.glob("*_content_list.json")):
                    existing = results.get(doc_id)
                    if existing is None or candidate.stat().st_mtime > existing.stat().st_mtime:
                        results[doc_id] = candidate
                    break
    return results


def build_rag_and_evidence(doc_id: str, artifact_dir: Path) -> bool:
    """Build RAG inputs and extract evidence. Returns True on success."""
    rag_out = RAG_DIR / doc_id
    ev_out = EVI_DIR / doc_id

    if rag_out.exists() and (rag_out / "rag_chunks.jsonl").exists():
        print(f"  SKIP {doc_id}: already done")
        return True

    # Build RAG inputs
    try:
        outputs = build_rag_inputs(
            artifact_dir=artifact_dir,
            source_pdf=f"{doc_id}.pdf",
            document_id=doc_id,
        )
        rag_out.mkdir(parents=True, exist_ok=True)
        write_json(rag_out / "document_manifest.json", outputs["manifest"])
        write_jsonl(rag_out / "rag_chunks.jsonl", outputs["rag_chunks"])
        write_jsonl(rag_out / "table_records.jsonl", outputs["table_records"])
        write_jsonl(rag_out / "extraction_candidates.jsonl", outputs["extraction_candidates"])
        c = outputs["manifest"]["counts"]
        print(f"  RAG {doc_id}: chunks={c['rag_chunks']} tables={c['table_records']} candidates={c['extraction_candidates']} pages={c['pages']}")
    except Exception as e:
        print(f"  FAIL RAG {doc_id}: {e}")
        return False

    # Extract evidence
    try:
        outputs = extract_evidence_records(rag_out)
        ev_out.mkdir(parents=True, exist_ok=True)
        write_jsonl(ev_out / "evidence_records.jsonl", outputs["evidence_records"])
        write_jsonl(ev_out / "review_queue.jsonl", outputs["review_queue"])
        write_json(ev_out / "validation_report.json", outputs["validation_report"])
        r = outputs["validation_report"]
        print(f"  EVI {doc_id}: records={r['output_counts']['evidence_records']} review={r['output_counts']['review_queue']}")
        return True
    except Exception as e:
        print(f"  FAIL EVI {doc_id}: {e}")
        return False


def submit_one_to_mineru(pdf_path: Path) -> Optional[str]:
    """Submit one PDF to MinerU, poll, return task_id or None."""
    name = normalize_doc_id(pdf_path.stem)
    options = MinerUOptions(
        return_model_output="false",
        return_middle_json="true",
        response_format_zip="true",
    )
    client = MinerUClient(submit_base_url=MINERU_URL, result_base_url=MINERU_URL, timeout=180.0)
    try:
        task_id, payload = client.submit_pdfs([pdf_path], options)
        print(f"  Submitted {name} -> task_id={task_id}")
        result = client.poll_until_done(task_id, timeout_seconds=1800, interval_seconds=15)
        print(f"  {name}: MinerU done, status={result.status}")
        return task_id
    except Exception as exc:
        print(f"  SKIP {name}: MinerU failed: {exc}")
        return None


def index_to_qdrant(doc_ids: list[str], recreate: bool = False) -> None:
    runtime_config = RuntimeConfig.from_file(CONFIG_PATH)
    emb = runtime_config.embedding
    if emb.provider == "sentence":
        model = SentenceEmbeddingModel(
            SentenceEmbeddingConfig(
                model_name=emb.model_name,
                dimensions=emb.dimensions,
                device=emb.device,
                cache_folder=emb.cache_folder,
                local_files_only=emb.local_files_only,
            )
        )
    else:
        from enzyme_recommender.rag.embedding import HashEmbeddingConfig, HashEmbeddingModel
        model = HashEmbeddingModel(HashEmbeddingConfig(dimensions=emb.dimensions))

    all_points = []
    for doc_id in doc_ids:
        rag_dir = RAG_DIR / doc_id
        ev_dir = EVI_DIR / doc_id
        if not rag_dir.exists() or not (rag_dir / "rag_chunks.jsonl").exists():
            continue
        ev_arg = ev_dir if ev_dir.exists() else None
        try:
            pts = build_index_points(rag_input_dir=rag_dir, evidence_dir=ev_arg, embedding_model=model)
            all_points.extend(pts)
            print(f"  {doc_id}: {len(pts)} points")
        except Exception as e:
            print(f"  FAIL {doc_id}: {e}")

    if not all_points:
        print("No points to index!")
        return

    print(f"\nTotal: {len(all_points)} points")
    counts = Counter(p["payload"]["point_type"] for p in all_points)
    print(f"By type: {dict(counts)}")

    qdrant_config = QdrantConfig(url=QDRANT_URL, collection=COLLECTION)
    with QdrantRestClient(qdrant_config) as client:
        client.ensure_collection(vector_size=model.dimensions, recreate=recreate)
        client.upsert_points(all_points, batch_size=64)
    print(f"Indexed to {COLLECTION}")


def main() -> None:
    # ── Phase 1: Process existing MinerU results ──
    existing = find_existing_mineru_results()
    print(f"Existing MinerU results with content_list: {len(existing)}")
    for doc_id, path in sorted(existing.items()):
        print(f"  {doc_id}: {path}")

    print(f"\n{'='*50}")
    print("PHASE 1: RAG inputs + evidence for existing MinerU results")
    print(f"{'='*50}")

    already = set()
    if RAG_DIR.exists():
        for d in RAG_DIR.iterdir():
            if d.is_dir() and (d / "rag_chunks.jsonl").exists():
                already.add(d.name)

    done = []
    for doc_id, artifact_dir in sorted(existing.items()):
        if doc_id in already:
            continue
        print(f"\n  Processing {doc_id}...")
        if build_rag_and_evidence(doc_id, artifact_dir):
            done.append(doc_id)

    print(f"\nPhase 1 complete: {len(done)} new docs processed, {len(already)} already existed")

    # ── Phase 2: Submit remaining PDFs to MinerU ──
    all_pdfs = sorted(PDF_DIR.glob("*.pdf"))
    processed_ids = set(find_existing_mineru_results().keys()) | already
    all_pdf_names = set()
    pdf_by_name: dict[str, Path] = {}
    for p in all_pdfs:
        name = normalize_doc_id(p.stem)
        all_pdf_names.add(name)
        if name not in pdf_by_name or len(p.stem) < len(pdf_by_name[name].stem):
            pdf_by_name[name] = p

    remaining = sorted(all_pdf_names - processed_ids)
    print(f"\n{'='*50}")
    print(f"PHASE 2: MinerU processing for {len(remaining)} remaining PDFs")
    print(f"{'='*50}")

    mineru_ok = []
    for i, name in enumerate(remaining):
        pdf_path = pdf_by_name[name]
        print(f"\n[{i+1}/{len(remaining)}] {name} ({pdf_path.stat().st_size // 1024} KB)...")
        task_id = submit_one_to_mineru(pdf_path)
        if task_id:
            # Check if artifact appeared
            results = find_existing_mineru_results()
            if name in results:
                mineru_ok.append(name)
                # Immediately process this new result
                print(f"  Processing {name} RAG + evidence immediately...")
                if build_rag_and_evidence(name, results[name]):
                    done.append(name)
            else:
                print(f"  WARNING: {name} submitted but artifact not found yet")

    # ── Phase 3: Process any new MinerU results ──
    if mineru_ok:
        print(f"\n{'='*50}")
        print(f"PHASE 3: RAG + evidence for {len(mineru_ok)} newly processed docs")
        print(f"{'='*50}")
        for doc_id in mineru_ok:
            if doc_id in done:
                continue
            results = find_existing_mineru_results()
            if doc_id in results:
                build_rag_and_evidence(doc_id, results[doc_id])

    # ── Phase 4: Index everything to Qdrant ──
    all_done = set()
    if RAG_DIR.exists():
        for d in RAG_DIR.iterdir():
            if d.is_dir() and (d / "rag_chunks.jsonl").exists():
                all_done.add(d.name)

    print(f"\n{'='*50}")
    print(f"PHASE 4: Index {len(all_done)} docs to Qdrant")
    print(f"{'='*50}")
    index_to_qdrant(sorted(all_done))

    # Final stats
    print(f"\n{'='*60}")
    print("FINAL SUMMARY")
    print(f"{'='*60}")
    print(f"Total docs with RAG inputs: {len(all_done)}")
    print(f"Total PDFs in collection: {len(all_pdfs)}")

    try:
        resp = httpx.get(f"{QDRANT_URL}/collections/{COLLECTION}", timeout=10)
        info = resp.json().get("result", {})
        print(f"Qdrant '{COLLECTION}': {info.get('points_count', '?')} points")
    except Exception as e:
        print(f"Qdrant stats error: {e}")


if __name__ == "__main__":
    main()
