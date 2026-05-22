"""RAG input builders and local retrieval utilities."""

from enzyme_recommender.rag.chunking import build_rag_inputs
from enzyme_recommender.rag.embedding import HashEmbeddingConfig, HashEmbeddingModel
from enzyme_recommender.rag.retrieval import EvidenceRetriever, RetrievalHit, RetrievalResponse

__all__ = [
    "EvidenceRetriever",
    "HashEmbeddingConfig",
    "HashEmbeddingModel",
    "RetrievalHit",
    "RetrievalResponse",
    "build_rag_inputs",
]
