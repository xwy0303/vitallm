from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, Union

from enzyme_recommender.rag.embedding import HashEmbeddingModel, SentenceEmbeddingModel


POINT_SCHEMA_VERSION = "point_schema_v1"
DEFAULT_COLLECTION_DOMAIN = "enzyme_immobilization"
DEFAULT_COLLECTION_CORPUS = "literature"


EmbeddingModel = Union[HashEmbeddingModel, SentenceEmbeddingModel]


@dataclass(frozen=True)
class IndexIdentity:
    collection: str
    index_version: str
    embedding_slug: str
    point_schema_version: str = POINT_SCHEMA_VERSION


def build_index_identity(
    embedding_model: EmbeddingModel,
    collection: Optional[str] = None,
    corpus: str = DEFAULT_COLLECTION_CORPUS,
    domain: str = DEFAULT_COLLECTION_DOMAIN,
    point_schema_version: str = POINT_SCHEMA_VERSION,
) -> IndexIdentity:
    embedding_slug = embedding_identity_slug(embedding_model)
    index_version = build_index_version(embedding_model, point_schema_version=point_schema_version)
    resolved_collection = resolve_collection_name(
        embedding_model=embedding_model,
        collection=collection,
        corpus=corpus,
        domain=domain,
        point_schema_version=point_schema_version,
    )
    return IndexIdentity(
        collection=resolved_collection,
        index_version=index_version,
        embedding_slug=embedding_slug,
        point_schema_version=point_schema_version,
    )


def resolve_collection_name(
    embedding_model: EmbeddingModel,
    collection: Optional[str] = None,
    corpus: str = DEFAULT_COLLECTION_CORPUS,
    domain: str = DEFAULT_COLLECTION_DOMAIN,
    point_schema_version: str = POINT_SCHEMA_VERSION,
) -> str:
    if collection and collection.strip() and collection.strip().lower() != "auto":
        return collection.strip()
    return build_collection_name(
        embedding_model=embedding_model,
        corpus=corpus,
        domain=domain,
        point_schema_version=point_schema_version,
    )


def build_collection_name(
    embedding_model: EmbeddingModel,
    corpus: str = DEFAULT_COLLECTION_CORPUS,
    domain: str = DEFAULT_COLLECTION_DOMAIN,
    point_schema_version: str = POINT_SCHEMA_VERSION,
) -> str:
    return "_".join(
        item
        for item in [
            slugify(domain),
            slugify(corpus),
            embedding_identity_slug(embedding_model),
            slugify(point_schema_version),
        ]
        if item
    )


def build_index_version(
    embedding_model: EmbeddingModel,
    point_schema_version: str = POINT_SCHEMA_VERSION,
) -> str:
    return f"idx_{embedding_identity_slug(embedding_model)}_{slugify(point_schema_version)}"


def embedding_identity_slug(embedding_model: EmbeddingModel) -> str:
    if isinstance(embedding_model, HashEmbeddingModel):
        return slugify(embedding_model.name)
    raw_name = embedding_model.name
    if raw_name.startswith("sentence:"):
        raw_name = raw_name.removeprefix("sentence:")
    return slugify(f"sentence_{raw_name}_{embedding_model.dimensions}")


def slugify(value: str) -> str:
    normalized = value.strip().lower()
    normalized = normalized.replace(":", "_").replace("/", "_")
    normalized = re.sub(r"[^a-z0-9]+", "_", normalized)
    normalized = re.sub(r"_+", "_", normalized)
    return normalized.strip("_")
