"""RAG input builders and local retrieval utilities."""

from enzyme_recommender.rag.chunking import build_rag_inputs
from enzyme_recommender.rag.embedding import HashEmbeddingConfig, HashEmbeddingModel
from enzyme_recommender.rag.indexing import (
    POINT_SCHEMA_VERSION,
    build_collection_name,
    build_index_identity,
    build_index_version,
    embedding_identity_slug,
    resolve_collection_name,
)
from enzyme_recommender.rag.retrieval import EvidenceRetriever, RetrievalHit, RetrievalResponse

__all__ = [
    "EvidenceRetriever",
    "HashEmbeddingConfig",
    "HashEmbeddingModel",
    "POINT_SCHEMA_VERSION",
    "RetrievalHit",
    "RetrievalResponse",
    "build_collection_name",
    "build_index_identity",
    "build_index_version",
    "build_rag_inputs",
    "embedding_identity_slug",
    "resolve_collection_name",
]
