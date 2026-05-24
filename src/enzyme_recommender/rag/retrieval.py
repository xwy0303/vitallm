from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field

from enzyme_recommender.rag.embedding import HashEmbeddingConfig, HashEmbeddingModel, SentenceEmbeddingModel
from enzyme_recommender.rag.qdrant import QdrantConfig, QdrantRestClient


PointType = Literal["rag_chunk", "table_record", "evidence_record"]


class RetrievalHit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    score: float
    point_type: str
    source_id: str
    parent_source_id: Optional[str] = None
    document_id: Optional[str] = None
    source_pdf: Optional[str] = None
    citation: Optional[str] = None
    page_start: Optional[int] = None
    page_end: Optional[int] = None
    section: Optional[str] = None
    record_type: Optional[str] = None
    confidence: Optional[str] = None
    quality_flags: List[str] = Field(default_factory=list)
    review_reasons: List[str] = Field(default_factory=list)
    requires_review: bool = False
    usable_for_ranking: bool = False
    extracted: Dict[str, Any] = Field(default_factory=dict)
    metrics: List[Dict[str, Any]] = Field(default_factory=list)
    text: str
    source_chunk_text: Optional[str] = None


class RetrievalResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str
    collection: str
    embedding_model: str
    top_k: int
    usable_only: bool
    point_type: Optional[str] = None
    hits: List[RetrievalHit]

    def context_text(self, max_chars_per_hit: int = 900) -> str:
        blocks = []
        for index, hit in enumerate(self.hits, start=1):
            text = hit.text[:max_chars_per_hit]
            blocks.append(
                "\n".join(
                    [
                        f"[{index}] score={hit.score:.4f} type={hit.point_type} record_type={hit.record_type or '-'}",
                        f"source_id={hit.source_id} citation={hit.citation or '-'} usable={hit.usable_for_ranking} flags={hit.quality_flags}",
                        f"extracted={hit.extracted}",
                        f"metrics={hit.metrics}",
                        f"text={text}",
                    ]
                )
            )
        return "\n\n".join(blocks)


class EvidenceRetriever:
    def __init__(
        self,
        qdrant_config: QdrantConfig,
        embedding_model: Optional[Union[HashEmbeddingModel, SentenceEmbeddingModel]] = None,
    ) -> None:
        self.qdrant_config = qdrant_config
        self.embedding_model = embedding_model or HashEmbeddingModel(HashEmbeddingConfig())

    def retrieve(
        self,
        query: str,
        top_k: int = 8,
        point_type: Optional[PointType] = None,
        usable_only: bool = True,
    ) -> RetrievalResponse:
        query_filter = build_qdrant_filter(point_type=point_type, usable_only=usable_only)
        with QdrantRestClient(self.qdrant_config) as client:
            raw_hits = client.search(
                vector=self.embedding_model.embed(query),
                top_k=top_k,
                query_filter=query_filter,
            )

        hits = [raw_hit_to_retrieval_hit(raw_hit) for raw_hit in raw_hits]
        return RetrievalResponse(
            query=query,
            collection=self.qdrant_config.collection,
            embedding_model=self.embedding_model.name,
            top_k=top_k,
            usable_only=usable_only,
            point_type=point_type,
            hits=hits,
        )


def build_qdrant_filter(point_type: Optional[str], usable_only: bool) -> Optional[Dict[str, Any]]:
    must: List[Dict[str, Any]] = []
    if point_type:
        must.append({"key": "point_type", "match": {"value": point_type}})
    if usable_only:
        must.append({"key": "usable_for_ranking", "match": {"value": True}})
    if not must:
        return None
    return {"must": must}


def raw_hit_to_retrieval_hit(raw_hit: Dict[str, Any]) -> RetrievalHit:
    payload = raw_hit.get("payload") or {}
    return RetrievalHit(
        score=float(raw_hit.get("score") or 0.0),
        point_type=str(payload.get("point_type") or ""),
        source_id=str(payload.get("source_id") or ""),
        parent_source_id=payload.get("parent_source_id"),
        document_id=payload.get("document_id"),
        source_pdf=payload.get("source_pdf"),
        citation=payload.get("citation"),
        page_start=payload.get("page_start"),
        page_end=payload.get("page_end"),
        section=payload.get("section"),
        record_type=payload.get("record_type"),
        confidence=payload.get("confidence"),
        quality_flags=list(payload.get("quality_flags") or []),
        review_reasons=list(payload.get("review_reasons") or []),
        requires_review=bool(payload.get("requires_review")),
        usable_for_ranking=bool(payload.get("usable_for_ranking")),
        extracted=dict(payload.get("extracted") or {}),
        metrics=list(payload.get("metrics") or []),
        text=str(payload.get("text") or ""),
    )
