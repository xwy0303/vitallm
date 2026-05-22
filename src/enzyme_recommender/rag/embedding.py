from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from typing import Iterable, List, Sequence


TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9\-]{1,}|[0-9]+(?:\.[0-9]+)?%?")

DOMAIN_ALIASES = {
    "bcl": ["burkholderia", "cepacia", "lipase"],
    "zif-8": ["zif", "mof", "metal", "organic", "framework"],
    "mof": ["metal", "organic", "framework"],
    "immobilization": ["immobilized", "carrier", "support"],
    "immobilisation": ["immobilized", "carrier", "support"],
    "transesterification": ["biodiesel", "esterification"],
    "reusability": ["reuse", "cycles", "stability"],
}


@dataclass(frozen=True)
class HashEmbeddingConfig:
    dimensions: int = 384
    include_bigrams: bool = True


class HashEmbeddingModel:
    """Deterministic local embedding for smoke tests and offline development.

    This is intentionally simple. It is good enough to verify vector DB plumbing
    and metadata filters, but it is not the final scientific retrieval model.
    """

    def __init__(self, config: HashEmbeddingConfig | None = None) -> None:
        self.config = config or HashEmbeddingConfig()

    @property
    def dimensions(self) -> int:
        return self.config.dimensions

    @property
    def name(self) -> str:
        return f"hash-v1-{self.config.dimensions}"

    def embed(self, text: str) -> List[float]:
        tokens = normalize_tokens(text)
        features = list(tokens)
        if self.config.include_bigrams:
            features.extend(f"{left}_{right}" for left, right in zip(tokens, tokens[1:]))

        vector = [0.0] * self.config.dimensions
        for feature in features:
            index, sign = hash_feature(feature, self.config.dimensions)
            vector[index] += sign

        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0:
            return vector
        return [value / norm for value in vector]


def normalize_tokens(text: str) -> List[str]:
    raw_tokens = [match.group(0).lower() for match in TOKEN_RE.finditer(text)]
    tokens: List[str] = []
    for token in raw_tokens:
        token = token.strip("-")
        if not token:
            continue
        tokens.append(token)
        tokens.extend(DOMAIN_ALIASES.get(token, []))
    return tokens


def hash_feature(feature: str, dimensions: int) -> tuple[int, float]:
    digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
    value = int.from_bytes(digest, byteorder="big", signed=False)
    index = value % dimensions
    sign = 1.0 if (value >> 63) == 0 else -1.0
    return index, sign


def embed_many(model: HashEmbeddingModel, texts: Iterable[str]) -> List[List[float]]:
    return [model.embed(text) for text in texts]


def weighted_document_text(parts: Sequence[str | None]) -> str:
    return "\n".join(part.strip() for part in parts if part and part.strip())
