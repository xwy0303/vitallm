#!/usr/bin/env python3
"""
Process ALL PDFs through full pipeline: MinerU → RAG inputs → Evidence → Qdrant.
Processes one PDF at a time through MinerU, skipping failures.
"""

from __future__ import annotations

import json
import os
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
RAG_DIR = PROJECT_DIR / "artifacts" / "rag_inputs"
EVI_DIR = PROJECT_DIR / "artifacts" / "evidence"
CONFIG_PATH = PROJECT_DIR / "configs" / "local.yaml"
MINERU_URL = "http://127.0.0.1:8000"
QDRANT_URL = "http://127.0.0.1:6333"
COLLECTION = "enzyme_immobilization_b10"


def normalize_doc_id(value: str) -> str:
    return value.strip()


def get_pdf_name(p: Path) -> str:
    """Get clean PDF name without .pdf, stripping trailing spaces."""
    return normalize_doc_id(p.stem)


def already_processed() -> set[str]:
    s: set[str] = set()
    if RAG_DIR.exists():
        for d in RAG_DIR.iterdir():
            if d.is_dir() and (d / "rag_chunks.jsonl").exists():
                s.add(d.name)
    return s


def submit_one_to_mineru(pdf_path: Path) -> Optional[str]:
    """Submit single PDF to MinerU, poll until done, return task_id or None."""
    name = get_pdf_name(pdf_path)
    options = MinerUOptions(
        return_model_output="false",
        return_middle_json="true",
        response_format_zip="true",
    )
    client = MinerUClient(
        submit_base_url=MINERU_URL,
        result_base_url=MINERU_URL,
        timeout=180.0,
    )
    try:
        task_id, payload = client.submit_pdfs([pdf_path], options)
        print(f"  Submitted {name} → task_id={task_id}")
        result = client.poll_until_done(task_id, timeout_seconds=1800, interval_seconds=15)
        print(f"  {name} MinerU done: status={result.status}")
        return task_id
    except Exception as exc:
        print(f"  {name} FAILED at MinerU: {exc}")
        return None


def get_artifact_dir_for(doc_id: str) -> Optional[Path]:
    """Find MinerU output artifact dir for a given doc ID in output/."""
    output_dir = PROJECT_DIR / "output"
    if not output_dir.exists():
        return None
    best: Optional[Path] = None
    for task_dir in output_dir.iterdir():
        if not task_dir.is_dir() or task_dir.name == "pdf":
            continue
        for doc_dir in task_dir.iterdir():
            if not doc_dir.is_dir():
                continue
            if normalize_doc_id(doc_dir.name) != doc_id:
                continue
            for method in ["hybrid_auto", "auto"]:
                candidate = doc_dir / method
                if candidate.is_dir() and list(candidate.glob("*_content_list.json")):
                    if best is None or candidate.stat().st_mtime > best.stat().st_mtime:
                        best = candidate
    return best


def main() -> None:
    processed = already_processed()
    print(f"Already processed (have RAG inputs): {len(processed)}")

    all_pdfs = sorted(PDF_DIR.glob("*.pdf"), key=get_pdf_name)
    to_process = [p for p in all_pdfs if get_pdf_name(p) not in processed]

    # Handle C6 space issue - prefer non-space symlink or original
    pdf_map: dict[str, Path] = {}
    for p in all_pdfs:
        name = get_pdf_name(p)
        if name in pdf_map:
            # Keep the shorter name (no trailing space)
            if len(p.stem) < len(pdf_map[name].stem):
                pdf_map[name] = p
        else:
            pdf_map[name] = p

    to_process_paths = [pdf_map[get_pdf_name(p)] for p in to_process]

    print(f"To process: {len(to_process_paths)}")
    for p in to_process_paths:
        print(f"  {get_pdf_name(p)} ({p.stat().st_size // 1024} KB)")

    # ── Step 1: MinerU ──
    print(f"\n{'='*50}")
    print("STEP 1: MinerU processing (one at a time)")
    print(f"{'='*50}")

    mineru_ok: list[str] = []
    for i, pdf_path in enumerate(to_process_paths):
        name = get_pdf_name(pdf_path)
        print(f"\n[{i+1}/{len(to_process_paths)}] {name}...")
        task_id = submit_one_to_mineru(pdf_path)
        if task_id:
            # Verify artifact exists
            artifact_dir = get_artifact_dir_for(name)
            if artifact_dir:
                mineru_ok.append(name)
                print(f"  {name}: artifact at {artifact_dir}")
            else:
                print(f"  WARNING: {name} MinerU succeeded but artifact not found in output/")

    # ── Step 2: Build RAG inputs ──
    print(f"\n{'='*50}")
    print("STEP 2: Build RAG inputs")
    print(f"{'='*50}")

    rag_ok: list[str] = []
    for name in mineru_ok:
        artifact_dir = get_artifact_dir_for(name)
        if not artifact_dir:
            print(f"  SKIP {name}: no artifact dir")
            continue
        rag_out = RAG_DIR / name
        if rag_out.exists() and (rag_out / "rag_chunks.jsonl").exists():
            print(f"  SKIP {name}: already has RAG inputs")
            rag_ok.append(name)
            continue
        try:
            outputs = build_rag_inputs(
                artifact_dir=artifact_dir,
                source_pdf=f"{name}.pdf",
                document_id=name,
            )
            rag_out.mkdir(parents=True, exist_ok=True)
            write_json(rag_out / "document_manifest.json", outputs["manifest"])
            write_jsonl(rag_out / "rag_chunks.jsonl", outputs["rag_chunks"])
            write_jsonl(rag_out / "table_records.jsonl", outputs["table_records"])
            write_jsonl(rag_out / "extraction_candidates.jsonl", outputs["extraction_candidates"])
            c = outputs["manifest"]["counts"]
            print(f"  OK {name}: chunks={c['rag_chunks']} tables={c['table_records']} candidates={c['extraction_candidates']} pages={c['pages']}")
            rag_ok.append(name)
        except Exception as e:
            print(f"  FAIL {name}: {e}")

    # ── Step 3: Extract evidence ──
    print(f"\n{'='*50}")
    print("STEP 3: Extract evidence records")
    print(f"{'='*50}")

    ev_ok: list[str] = []
    for name in rag_ok:
        rag_dir = RAG_DIR / name
        ev_out = EVI_DIR / name
        if ev_out.exists() and (ev_out / "evidence_records.jsonl").exists():
            print(f"  SKIP {name}: already has evidence")
            ev_ok.append(name)
            continue
        try:
            outputs = extract_evidence_records(rag_dir)
            ev_out.mkdir(parents=True, exist_ok=True)
            write_jsonl(ev_out / "evidence_records.jsonl", outputs["evidence_records"])
            write_jsonl(ev_out / "review_queue.jsonl", outputs["review_queue"])
            write_json(ev_out / "validation_report.json", outputs["validation_report"])
            r = outputs["validation_report"]
            print(f"  OK {name}: evidence={r['output_counts']['evidence_records']} review={r['output_counts']['review_queue']}")
            ev_ok.append(name)
        except Exception as e:
            print(f"  FAIL {name}: {e}")

    # ── Step 4: Index to Qdrant ──
    print(f"\n{'='*50}")
    print("STEP 4: Index to Qdrant")
    print(f"{'='*50}")

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
    all_to_index = sorted(set(rag_ok) | set(ev_ok) | (processed - {"B1", "B2", "B3", "B4", "B5", "B10"}))
    for name in all_to_index:
        rag_dir = RAG_DIR / name
        ev_dir = EVI_DIR / name
        if not rag_dir.exists():
            continue
        ev_arg = ev_dir if ev_dir.exists() else None
        try:
            pts = build_index_points(rag_input_dir=rag_dir, evidence_dir=ev_arg, embedding_model=model)
            all_points.extend(pts)
            print(f"  {name}: {len(pts)} points")
        except Exception as e:
            print(f"  FAIL {name}: {e}")

    print(f"\nTotal: {len(all_points)} points")
    counts = Counter(p["payload"]["point_type"] for p in all_points)
    print(f"By type: {dict(counts)}")

    qdrant_config = QdrantConfig(url=QDRANT_URL, collection=COLLECTION)
    with QdrantRestClient(qdrant_config) as client:
        client.ensure_collection(vector_size=model.dimensions, recreate=False)
        client.upsert_points(all_points, batch_size=64)

    print(f"Indexed to {COLLECTION}")

    # Summary
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    print(f"MinerU processed: {len(mineru_ok)}")
    print(f"RAG inputs built: {len(rag_ok)}")
    print(f"Evidence extracted: {len(ev_ok)}")
    print(f"Indexed to Qdrant: {len(all_to_index)}")

    try:
        resp = httpx.get(f"{QDRANT_URL}/collections/{COLLECTION}", timeout=10)
        info = resp.json().get("result", {})
        print(f"\nQdrant '{COLLECTION}': {info.get('points_count', '?')} points")
    except Exception:
        pass


if __name__ == "__main__":
    main()
