from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from enzyme_recommender.generators.openai_compatible import OpenAICompatibleGeneratorClient
from enzyme_recommender.generators.protocol import GeneratorClient, MockGeneratorClient
from enzyme_recommender.ingestion import MinerUClient
from enzyme_recommender.rag.embedding import (
    HashEmbeddingConfig,
    HashEmbeddingModel,
    SentenceEmbeddingConfig,
    SentenceEmbeddingModel,
)
from enzyme_recommender.rag.qdrant import QdrantConfig
from enzyme_recommender.rag.retrieval import EvidenceRetriever
from enzyme_recommender.rag.indexing import build_index_identity
from enzyme_recommender.runtime.config import RuntimeConfig


@dataclass(frozen=True)
class RuntimeServices:
    config: RuntimeConfig

    @classmethod
    def from_config_file(cls, path: Path | str) -> "RuntimeServices":
        return cls(config=RuntimeConfig.from_file(path))

    def document_parser(self) -> MinerUClient:
        parser_config = self.config.document_parser
        return MinerUClient(
            submit_base_url=parser_config.submit_base_url,
            result_base_url=parser_config.result_base_url,
            timeout=parser_config.timeout_seconds,
        )

    def embedding_model(self) -> HashEmbeddingModel | SentenceEmbeddingModel:
        embedding_config = self.config.embedding
        if embedding_config.provider == "sentence":
            return SentenceEmbeddingModel(
                SentenceEmbeddingConfig(
                    model_name=embedding_config.model_name,
                    dimensions=embedding_config.dimensions,
                    device=embedding_config.device,
                    cache_folder=embedding_config.cache_folder,
                    local_files_only=embedding_config.local_files_only,
                )
            )
        return HashEmbeddingModel(HashEmbeddingConfig(dimensions=embedding_config.dimensions))

    def qdrant_config(self) -> QdrantConfig:
        vector_config = self.config.vector_store
        collection = build_index_identity(
            embedding_model=self.embedding_model(),
            collection=vector_config.collection,
        ).collection
        return QdrantConfig(
            url=vector_config.url,
            collection=collection,
            timeout=vector_config.timeout_seconds,
        )

    def retriever(self) -> EvidenceRetriever:
        return EvidenceRetriever(
            qdrant_config=self.qdrant_config(),
            embedding_model=self.embedding_model(),
        )

    def generator(self) -> GeneratorClient:
        provider = self.config.generator.provider
        provider_config = self.config.generator_providers[provider]
        if provider == "mock":
            return MockGeneratorClient()
        return OpenAICompatibleGeneratorClient(
            provider=provider,
            base_url=provider_config.base_url or "",
            api_key=self.config.require_generator_api_key(),
            timeout_seconds=self.config.generator.timeout_seconds,
        )
