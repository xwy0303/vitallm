from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from enzyme_recommender.rag.indexing import build_index_identity
from enzyme_recommender.rag.qdrant import QdrantConfig, QdrantRestClient, build_index_points, point_type_counts
from enzyme_recommender.runtime import RuntimeServices


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Rebuild a Qdrant collection from existing RAG/evidence artifacts without rerunning MinerU."
    )
    parser.add_argument("--config", default=Path("configs/local.yaml"), type=Path)
    parser.add_argument("--artifact-root", default=Path("artifacts"), type=Path)
    parser.add_argument("--collection", default=None)
    parser.add_argument("--collection-corpus", default="literature")
    parser.add_argument("--document-id", action="append", default=None)
    parser.add_argument("--limit", default=None, type=int)
    parser.add_argument("--batch-size", default=64, type=int)
    parser.add_argument("--recreate", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--manifest", default=None, type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    runtime = RuntimeServices.from_config_file(args.config)
    embedding_model = runtime.embedding_model()
    collection_override = args.collection or runtime.config.vector_store.collection
    index_identity = build_index_identity(
        embedding_model=embedding_model,
        collection=collection_override,
        corpus=args.collection_corpus,
    )
    qdrant_config = QdrantConfig(
        url=runtime.config.vector_store.url,
        collection=index_identity.collection,
        timeout=runtime.config.vector_store.timeout_seconds,
    )
    document_ids = set(args.document_id or [])
    document_dirs = list(iter_document_dirs(args.artifact_root / "rag_inputs", document_ids=document_ids))
    if args.limit is not None:
        document_dirs = document_dirs[: args.limit]
    if not document_dirs:
        raise SystemExit("No RAG input directories found.")

    print(f"Collection: {index_identity.collection}")
    print(f"Index version: {index_identity.index_version}")
    print(f"Point schema: {index_identity.point_schema_version}")
    print(f"Embedding model: {embedding_model.name}")
    print(f"Documents: {len(document_dirs)}")

    extra_payload = {
        "point_schema_version": index_identity.point_schema_version,
        "embedding_model": embedding_model.name,
        "embedding_dimensions": embedding_model.dimensions,
        "embedding_slug": index_identity.embedding_slug,
        "index_version": index_identity.index_version,
    }
    totals: Dict[str, int] = {}
    document_reports: List[Dict[str, Any]] = []
    client: Optional[QdrantRestClient] = None
    if not args.dry_run:
        client = QdrantRestClient(qdrant_config)
        client.ensure_collection(vector_size=embedding_model.dimensions, recreate=args.recreate)
    try:
        for index, rag_dir in enumerate(document_dirs, start=1):
            document_id = rag_dir.name
            evidence_dir = args.artifact_root / "evidence" / document_id
            points = build_index_points(
                rag_input_dir=rag_dir,
                evidence_dir=evidence_dir if evidence_dir.is_dir() else None,
                embedding_model=embedding_model,
                extra_payload=extra_payload,
                index_version=index_identity.index_version,
            )
            counts = point_type_counts(points)
            for key, value in counts.items():
                totals[key] = totals.get(key, 0) + value
            document_reports.append(
                {
                    "document_id": document_id,
                    "rag_input_dir": str(rag_dir),
                    "evidence_dir": str(evidence_dir) if evidence_dir.is_dir() else None,
                    "point_counts": counts,
                    "points_total": len(points),
                }
            )
            if client is not None:
                client.upsert_points(points, batch_size=args.batch_size)
            print(f"[{index}/{len(document_dirs)}] {document_id} points={len(points)} counts={counts}")
    finally:
        if client is not None:
            client.close()

    summary = {
        "collection": index_identity.collection,
        "index_version": index_identity.index_version,
        "point_schema_version": index_identity.point_schema_version,
        "embedding_model": embedding_model.name,
        "embedding_dimensions": embedding_model.dimensions,
        "documents": len(document_reports),
        "point_counts": totals,
        "points_total": sum(totals.values()),
        "dry_run": args.dry_run,
        "document_reports": document_reports,
    }
    manifest_path = args.manifest or (
        args.artifact_root
        / "indexing"
        / f"{index_identity.collection}.reindex_manifest.json"
    )
    if not args.dry_run:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"WROTE {manifest_path}")
    print(json.dumps({key: summary[key] for key in summary if key != "document_reports"}, ensure_ascii=False, indent=2))


def iter_document_dirs(rag_root: Path, document_ids: Iterable[str]) -> List[Path]:
    allowed = set(document_ids)
    dirs = [
        path
        for path in rag_root.iterdir()
        if path.is_dir()
        and (path / "rag_chunks.jsonl").is_file()
        and (not allowed or path.name in allowed)
    ]
    return sorted(dirs, key=lambda path: path.name)


if __name__ == "__main__":
    main()
