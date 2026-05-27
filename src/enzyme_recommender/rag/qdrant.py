from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

import httpx

from enzyme_recommender.rag.embedding import (
    HashEmbeddingModel,
    SentenceEmbeddingModel,
    embed_many,
    weighted_document_text,
)
from enzyme_recommender.rag.indexing import POINT_SCHEMA_VERSION


Point = Dict[str, Any]
PAYLOAD_INDEX_FIELDS: Dict[str, str] = {
    "point_type": "keyword",
    "record_type": "keyword",
    "document_id": "keyword",
    "source_pdf": "keyword",
    "candidate_source": "keyword",
    "curation_status": "keyword",
    "qa_status": "keyword",
    "usable_for_ranking": "bool",
    "requires_review": "bool",
}


@dataclass(frozen=True)
class QdrantConfig:
    url: str = "http://127.0.0.1:6333"
    collection: str = "enzyme_immobilization"
    timeout: float = 30.0


class QdrantRestClient:
    def __init__(self, config: QdrantConfig) -> None:
        self.config = config
        self.base_url = config.url.rstrip("/")
        self.client = httpx.Client(timeout=config.timeout, trust_env=False)

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> "QdrantRestClient":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def ensure_collection(self, vector_size: int, recreate: bool = False) -> None:
        if recreate:
            self.delete_collection()

        collection_info = self.get_collection_info()
        if collection_info is not None:
            existing_size = extract_collection_vector_size(collection_info)
            if existing_size is None:
                raise RuntimeError(
                    f"cannot determine vector size for Qdrant collection '{self.config.collection}'; "
                    "use a single-vector collection or recreate it for this pipeline."
                )
            if existing_size != vector_size:
                raise RuntimeError(
                    f"Qdrant collection '{self.config.collection}' has vector size {existing_size}, "
                    f"but the embedding model produces {vector_size}. "
                    "Use --recreate or choose a collection indexed with the same embedding model."
                )
            return

        response = self._request(
            "PUT",
            f"/collections/{self.config.collection}",
            json={
                "vectors": {
                    "size": vector_size,
                    "distance": "Cosine",
                }
            },
        )
        if response.status_code == 409:
            collection_info = self.get_collection_info()
            existing_size = extract_collection_vector_size(collection_info or {})
            if existing_size == vector_size:
                return
        if response.status_code not in {200, 201}:
            raise RuntimeError(f"Qdrant collection setup failed: {response.status_code} {response.text}")

    def upsert_points(self, points: Sequence[Point], batch_size: int = 64) -> None:
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        if not points:
            return
        for start in range(0, len(points), batch_size):
            batch = points[start : start + batch_size]
            response = self._request(
                "PUT",
                f"/collections/{self.config.collection}/points",
                json={"points": batch},
            )
            if response.status_code not in {200, 201}:
                raise RuntimeError(f"Qdrant upsert failed: {response.status_code} {response.text}")

    def delete_points_by_filter(self, query_filter: Dict[str, Any]) -> None:
        response = self._request(
            "POST",
            f"/collections/{self.config.collection}/points/delete",
            json={"filter": query_filter},
        )
        if response.status_code not in {200, 202}:
            raise RuntimeError(f"Qdrant delete failed: {response.status_code} {response.text}")

    def create_payload_index(self, field_name: str, field_schema: str = "keyword", wait: bool = True) -> None:
        response = self._request(
            "PUT",
            f"/collections/{self.config.collection}/index",
            params={"wait": str(wait).lower()},
            json={"field_name": field_name, "field_schema": field_schema},
        )
        if response.status_code not in {200, 201}:
            raise RuntimeError(
                f"Qdrant payload index setup failed for {field_name}: {response.status_code} {response.text}"
            )

    def ensure_payload_indexes(self, fields: Optional[Dict[str, str]] = None, wait: bool = True) -> None:
        for field_name, field_schema in (fields or PAYLOAD_INDEX_FIELDS).items():
            self.create_payload_index(field_name, field_schema, wait=wait)

    def list_payload_schema(self) -> Dict[str, Any]:
        collection_info = self.get_collection_info()
        if collection_info is None:
            raise RuntimeError(f"Qdrant collection does not exist: {self.config.collection}")
        payload_schema = collection_info.get("payload_schema") or {}
        if not isinstance(payload_schema, dict):
            raise RuntimeError(f"unexpected Qdrant payload schema: {payload_schema}")
        return payload_schema

    def search(
        self,
        vector: Sequence[float],
        top_k: int = 10,
        query_filter: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        if top_k <= 0:
            raise ValueError("top_k must be positive")
        collection_info = self.get_collection_info()
        if collection_info is None:
            raise RuntimeError(f"Qdrant collection does not exist: {self.config.collection}")
        existing_size = extract_collection_vector_size(collection_info)
        if existing_size is None:
            raise RuntimeError(
                f"cannot determine vector size for Qdrant collection '{self.config.collection}'; "
                "use a single-vector collection or recreate it for this pipeline."
            )
        if existing_size != len(vector):
            raise RuntimeError(
                f"Qdrant collection '{self.config.collection}' has vector size {existing_size}, "
                f"but query vector has size {len(vector)}. Use the embedding model that built this collection."
            )
        payload: Dict[str, Any] = {
            "vector": list(vector),
            "limit": top_k,
            "with_payload": True,
        }
        if query_filter:
            payload["filter"] = query_filter

        response = self._request(
            "POST",
            f"/collections/{self.config.collection}/points/search",
            json=payload,
        )
        if response.status_code != 200:
            raise RuntimeError(f"Qdrant search failed: {response.status_code} {response.text}")
        result = response.json().get("result")
        if not isinstance(result, list):
            raise RuntimeError(f"unexpected Qdrant search response: {response.text}")
        return result

    def scroll_payloads(
        self,
        query_filter: Dict[str, Any],
        limit: int = 32,
    ) -> List[Dict[str, Any]]:
        if limit <= 0:
            raise ValueError("limit must be positive")
        response = self._request(
            "POST",
            f"/collections/{self.config.collection}/points/scroll",
            json={
                "filter": query_filter,
                "limit": limit,
                "with_payload": True,
                "with_vector": False,
            },
        )
        if response.status_code != 200:
            raise RuntimeError(f"Qdrant scroll failed: {response.status_code} {response.text}")
        points = response.json().get("result", {}).get("points")
        if not isinstance(points, list):
            raise RuntimeError(f"unexpected Qdrant scroll response: {response.text}")
        return [dict(point.get("payload") or {}) for point in points]

    def scroll_points(
        self,
        query_filter: Dict[str, Any],
        limit: int = 256,
        with_vector: bool = False,
    ) -> List[Dict[str, Any]]:
        if limit <= 0:
            raise ValueError("limit must be positive")
        points: List[Dict[str, Any]] = []
        offset: Optional[Any] = None
        while True:
            payload: Dict[str, Any] = {
                "filter": query_filter,
                "limit": limit,
                "with_payload": True,
                "with_vector": with_vector,
            }
            if offset is not None:
                payload["offset"] = offset
            response = self._request(
                "POST",
                f"/collections/{self.config.collection}/points/scroll",
                json=payload,
            )
            if response.status_code != 200:
                raise RuntimeError(f"Qdrant scroll failed: {response.status_code} {response.text}")
            result = response.json().get("result")
            if not isinstance(result, dict):
                raise RuntimeError(f"unexpected Qdrant scroll response: {response.text}")
            batch = result.get("points")
            if not isinstance(batch, list):
                raise RuntimeError(f"unexpected Qdrant scroll response: {response.text}")
            points.extend(dict(point) for point in batch)
            offset = result.get("next_page_offset")
            if offset is None:
                return points

    def count_points(self, query_filter: Dict[str, Any], exact: bool = True) -> int:
        response = self._request(
            "POST",
            f"/collections/{self.config.collection}/points/count",
            json={
                "filter": query_filter,
                "exact": exact,
            },
        )
        if response.status_code != 200:
            raise RuntimeError(f"Qdrant count failed: {response.status_code} {response.text}")
        count = response.json().get("result", {}).get("count")
        if not isinstance(count, int):
            raise RuntimeError(f"unexpected Qdrant count response: {response.text}")
        return count

    def scroll_all_payloads(
        self,
        limit: int = 256,
        with_payload: bool | Sequence[str] = True,
    ) -> List[Dict[str, Any]]:
        if limit <= 0:
            raise ValueError("limit must be positive")
        payloads: List[Dict[str, Any]] = []
        offset: Optional[Any] = None
        while True:
            request_payload: Dict[str, Any] = {
                "limit": limit,
                "with_payload": with_payload,
                "with_vector": False,
            }
            if offset is not None:
                request_payload["offset"] = offset
            response = self._request(
                "POST",
                f"/collections/{self.config.collection}/points/scroll",
                json=request_payload,
            )
            if response.status_code != 200:
                raise RuntimeError(f"Qdrant scroll failed: {response.status_code} {response.text}")
            result = response.json().get("result")
            if not isinstance(result, dict):
                raise RuntimeError(f"unexpected Qdrant scroll response: {response.text}")
            points = result.get("points")
            if not isinstance(points, list):
                raise RuntimeError(f"unexpected Qdrant scroll response: {response.text}")
            payloads.extend(dict(point.get("payload") or {}) for point in points)
            offset = result.get("next_page_offset")
            if offset is None:
                return payloads

    def get_collection_info(self) -> Optional[Dict[str, Any]]:
        response = self._request("GET", f"/collections/{self.config.collection}")
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            raise RuntimeError(f"Qdrant collection inspect failed: {response.status_code} {response.text}")
        payload = response.json()
        result = payload.get("result")
        if not isinstance(result, dict):
            raise RuntimeError(f"unexpected Qdrant collection response: {response.text}")
        return result

    def delete_collection(self) -> None:
        response = self._request("DELETE", f"/collections/{self.config.collection}")
        if response.status_code not in {200, 202, 404}:
            raise RuntimeError(f"Qdrant collection delete failed: {response.status_code} {response.text}")

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        url = f"{self.base_url}{path}"
        try:
            return self.client.request(method, url, **kwargs)
        except httpx.TransportError as exc:
            raise RuntimeError(
                f"cannot connect to Qdrant at {self.base_url}; "
                "start the local service first with scripts/start_qdrant_local.sh"
            ) from exc


def extract_collection_vector_size(collection_info: Dict[str, Any]) -> Optional[int]:
    vectors = (
        collection_info.get("config", {})
        .get("params", {})
        .get("vectors")
    )
    if isinstance(vectors, dict) and isinstance(vectors.get("size"), int):
        return vectors["size"]
    if isinstance(vectors, dict):
        sizes = {
            value.get("size")
            for value in vectors.values()
            if isinstance(value, dict) and isinstance(value.get("size"), int)
        }
        if len(sizes) == 1:
            return sizes.pop()
    return None


def load_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            payload = json.loads(line)
            if not isinstance(payload, dict):
                raise ValueError(f"expected JSON object at {path}:{line_number}")
            rows.append(payload)
    return rows


def build_index_points(
    rag_input_dir: Path,
    evidence_dir: Optional[Path],
    embedding_model: HashEmbeddingModel | SentenceEmbeddingModel,
    extra_payload: Optional[Dict[str, Any]] = None,
    index_version: Optional[str] = None,
) -> List[Point]:
    rows: List[Dict[str, Any]] = []
    rows.extend(chunk_to_document(row) for row in load_jsonl(rag_input_dir / "rag_chunks.jsonl"))
    rows.extend(table_to_document(row) for row in load_jsonl(rag_input_dir / "table_records.jsonl"))

    if evidence_dir is not None and (evidence_dir / "evidence_records.jsonl").exists():
        rows.extend(evidence_to_document(row) for row in load_jsonl(evidence_dir / "evidence_records.jsonl"))
    if evidence_dir is not None and (evidence_dir / "curated_evidence_records.jsonl").exists():
        rows.extend(evidence_to_document(row) for row in load_jsonl(evidence_dir / "curated_evidence_records.jsonl"))

    embedding_texts: List[str] = []
    payload_rows: List[Dict[str, Any]] = []
    for row in rows:
        payload_row = dict(row)
        embedding_texts.append(str(payload_row.pop("_embedding_text")))
        payload_rows.append(payload_row)

    vectors = embed_many(embedding_model, embedding_texts)
    if len(vectors) != len(payload_rows):
        raise RuntimeError(f"embedding model returned {len(vectors)} vectors for {len(payload_rows)} documents")

    points: List[Point] = []
    for row, vector in zip(payload_rows, vectors):
        if extra_payload:
            row.update(extra_payload)
        if index_version:
            row.setdefault("index_version", index_version)
            row.setdefault("point_schema_version", POINT_SCHEMA_VERSION)
        point_id_key = row["payload_key"] if not index_version else f"{row['payload_key']}:{index_version}"
        point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, point_id_key))
        points.append(
            {
                "id": point_id,
                "vector": vector,
                "payload": row,
            }
        )
    return points


def chunk_to_document(chunk: Dict[str, Any]) -> Dict[str, Any]:
    text = str(chunk.get("text") or "")
    quality_flags = list(chunk.get("quality_flags") or [])
    requires_review = bool(chunk.get("requires_review") or quality_flags)
    usable_for_ranking = bool(chunk.get("usable_for_ranking", not requires_review)) and not requires_review
    embedding_text = weighted_document_text(
        [
            chunk.get("section"),
            " ".join(chunk.get("signals") or []),
            text,
        ]
    )
    return {
        "payload_key": f"chunk:{chunk.get('chunk_id')}",
        "point_type": "rag_chunk",
        "document_id": chunk.get("document_id"),
        "source_pdf": chunk.get("source_pdf"),
        "source_id": chunk.get("chunk_id"),
        "chunk_type": chunk.get("chunk_type"),
        "page_start": chunk.get("page_start"),
        "page_end": chunk.get("page_end"),
        "section": chunk.get("section"),
        "signals": chunk.get("signals") or [],
        "quality_flags": quality_flags,
        "qa_status": chunk.get("qa_status"),
        "qa_flags": chunk.get("qa_flags") or [],
        "review_reasons": chunk.get("review_reasons") or [],
        "requires_review": requires_review,
        "usable_for_ranking": usable_for_ranking,
        "citation": citation(chunk),
        "text": text,
        "embedding_text": embedding_text,
        "_embedding_text": embedding_text,
    }


def table_to_document(table: Dict[str, Any]) -> Dict[str, Any]:
    text = weighted_document_text([table.get("caption"), table.get("text")])
    quality_flags = list(table.get("quality_flags") or [])
    requires_review = bool(table.get("requires_review") or quality_flags)
    usable_for_ranking = bool(table.get("usable_for_ranking", not requires_review)) and not requires_review
    rows = table.get("rows") or []
    row_preview = ""
    if isinstance(rows, list):
        row_preview = " ".join(
            " | ".join(str(cell) for cell in row[:12])
            for row in rows[:8]
            if isinstance(row, list)
        )
    embedding_text = weighted_document_text(
        [
            table.get("section"),
            table.get("caption"),
            " ".join(table.get("signals") or []),
            " ".join(str(column) for column in (table.get("columns") or [])),
            row_preview,
            text,
        ]
    )
    return {
        "payload_key": f"table:{table.get('table_id')}",
        "point_type": "table_record",
        "document_id": table.get("document_id"),
        "source_pdf": table.get("source_pdf"),
        "source_id": table.get("table_id"),
        "page_start": table.get("page_idx"),
        "page_end": table.get("page_idx"),
        "section": table.get("section"),
        "signals": table.get("signals") or [],
        "quality_flags": quality_flags,
        "qa_status": table.get("qa_status"),
        "qa_flags": table.get("qa_flags") or [],
        "review_reasons": table.get("review_reasons") or [],
        "requires_review": requires_review,
        "usable_for_ranking": usable_for_ranking,
        "citation": citation({"source_pdf": table.get("source_pdf"), "page_start": table.get("page_idx"), "page_end": table.get("page_idx")}),
        "caption": table.get("caption"),
        "columns": table.get("columns") or [],
        "row_count": table.get("row_count"),
        "text": text,
        "embedding_text": embedding_text,
        "_embedding_text": embedding_text,
    }


def evidence_to_document(record: Dict[str, Any]) -> Dict[str, Any]:
    extracted = record.get("extracted") or {}
    metrics = record.get("metrics") or []
    quality_flags = list(record.get("quality_flags") or [])
    if record.get("candidate_source") == "curated_evidence":
        requires_review = bool(record.get("requires_review"))
    else:
        requires_review = bool(record.get("requires_review") or quality_flags)
    usable_for_ranking = bool(record.get("usable_for_ranking", not requires_review)) and not requires_review
    text = weighted_document_text(
        [
            record.get("section"),
            record.get("record_type"),
            json.dumps(extracted, ensure_ascii=False, sort_keys=True),
            json.dumps(metrics, ensure_ascii=False, sort_keys=True),
            record.get("evidence_span"),
        ]
    )
    return {
        "payload_key": f"evidence:{record.get('evidence_id')}",
        "point_type": "evidence_record",
        "document_id": record.get("document_id"),
        "source_pdf": record.get("source_pdf"),
        "source_id": record.get("evidence_id"),
        "parent_source_id": record.get("source_id"),
        "source_evidence_id": record.get("source_evidence_id"),
        "record_type": record.get("record_type"),
        "page_start": record.get("page_start"),
        "page_end": record.get("page_end"),
        "section": record.get("section"),
        "quality_flags": quality_flags,
        "qa_status": record.get("qa_status"),
        "qa_flags": record.get("qa_flags") or [],
        "review_reasons": record.get("review_reasons") or [],
        "requires_review": requires_review,
        "usable_for_ranking": usable_for_ranking,
        "confidence": record.get("confidence"),
        "candidate_source": record.get("candidate_source"),
        "curation_schema_version": record.get("curation_schema_version"),
        "curation_status": record.get("curation_status"),
        "curation_reason": record.get("curation_reason"),
        "reviewed_by": record.get("reviewed_by"),
        "reviewed_at": record.get("reviewed_at"),
        "citation": citation(record),
        "extracted": extracted,
        "metrics": metrics,
        "text": record.get("evidence_span") or "",
        "embedding_text": text,
        "_embedding_text": text,
    }


def citation(row: Dict[str, Any]) -> str:
    source_pdf = row.get("source_pdf") or row.get("document_id") or "<unknown>"
    page_start = row.get("page_start")
    page_end = row.get("page_end", page_start)
    if page_start is None:
        return str(source_pdf)
    if page_end is None or page_end == page_start:
        return f"{source_pdf}:p{display_page_number(page_start)}"
    return f"{source_pdf}:p{display_page_number(page_start)}-p{display_page_number(page_end)}"


def display_page_number(page_index: Any) -> Any:
    """MinerU page_idx is 0-based; citations and PDF viewers are 1-based."""
    try:
        return int(page_index) + 1
    except (TypeError, ValueError):
        return page_index


def point_type_counts(points: Iterable[Point]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for point in points:
        point_type = str(point.get("payload", {}).get("point_type") or "<missing>")
        counts[point_type] = counts.get(point_type, 0) + 1
    return counts
