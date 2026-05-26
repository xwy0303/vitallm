from __future__ import annotations

import hashlib
import math
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, List, Optional, Sequence


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


def embed_many(model: HashEmbeddingModel | SentenceEmbeddingModel, texts: Iterable[str]) -> List[List[float]]:
    if isinstance(model, SentenceEmbeddingModel):
        return model.embed_many(texts)
    return [model.embed(text) for text in texts]


def weighted_document_text(parts: Sequence[str | None]) -> str:
    return "\n".join(part.strip() for part in parts if part and part.strip())


@dataclass(frozen=True)
class SentenceEmbeddingConfig:
    model_name: str = "BAAI/bge-base-en-v1.5"
    dimensions: int = 768
    device: str = "mps"
    normalize_embeddings: bool = True
    cache_folder: Optional[str] = None
    local_files_only: bool = False


class SentenceEmbeddingModel:
    """Semantic embedding via sentence-transformers.

    Uses BGE or compatible model for meaningful vector representations.
    Model is lazy-loaded on first call to avoid import overhead.
    """

    def __init__(self, config: Optional[SentenceEmbeddingConfig] = None) -> None:
        self.config = config or SentenceEmbeddingConfig()
        self._model: Any = None
        self._load_lock = threading.Lock()

    @property
    def dimensions(self) -> int:
        return self.config.dimensions

    @property
    def name(self) -> str:
        return f"sentence:{self.config.model_name}"

    def embed(self, text: str) -> List[float]:
        model = self._load_model()
        vector = model.encode(text, normalize_embeddings=self.config.normalize_embeddings)
        return self._normalize_vector(vector)

    def embed_many(self, texts: Iterable[str]) -> List[List[float]]:
        model = self._load_model()
        batch = list(texts)
        if not batch:
            return []
        vectors = model.encode(batch, normalize_embeddings=self.config.normalize_embeddings)
        return [self._normalize_vector(vec) for vec in vectors]

    def _load_model(self) -> Any:
        if self._model is not None:
            return self._model
        with self._load_lock:
            if self._model is not None:
                return self._model
            from sentence_transformers import SentenceTransformer

            cache_folder = str(Path(self.config.cache_folder).expanduser()) if self.config.cache_folder else None
            try:
                self._model = SentenceTransformer(
                    self.config.model_name,
                    device=self.config.device,
                    cache_folder=cache_folder,
                    local_files_only=self.config.local_files_only,
                )
            except RuntimeError as exc:
                if not is_meta_tensor_load_error(exc):
                    raise
                self._model = TransformersClsPoolingEncoder(self.config, cache_folder=cache_folder)
            actual_dimensions = self._model.get_sentence_embedding_dimension()
            if actual_dimensions != self.config.dimensions:
                raise ValueError(
                    f"embedding dimension mismatch for {self.config.model_name}: "
                    f"config={self.config.dimensions}, model={actual_dimensions}"
                )
            return self._model

    def _normalize_vector(self, vector: Any) -> List[float]:
        values = list(map(float, vector))
        if len(values) != self.config.dimensions:
            raise ValueError(
                f"embedding vector dimension mismatch for {self.config.model_name}: "
                f"config={self.config.dimensions}, vector={len(values)}"
            )
        return values


class TransformersClsPoolingEncoder:
    def __init__(self, config: SentenceEmbeddingConfig, cache_folder: Optional[str]) -> None:
        import torch
        from transformers import AutoModel, AutoTokenizer

        self.config = config
        self._torch = torch
        self._tokenizer = AutoTokenizer.from_pretrained(
            config.model_name,
            cache_dir=cache_folder,
            local_files_only=config.local_files_only,
        )
        self._model = AutoModel.from_pretrained(
            config.model_name,
            cache_dir=cache_folder,
            local_files_only=config.local_files_only,
        )
        self._device = torch.device(config.device or "cpu")
        self._model.to(self._device)
        self._model.eval()

    def get_sentence_embedding_dimension(self) -> Optional[int]:
        return getattr(self._model.config, "hidden_size", None)

    def encode(self, texts: str | Iterable[str], normalize_embeddings: bool = True) -> Any:
        import torch.nn.functional as functional

        is_single = isinstance(texts, str)
        batch = [texts] if is_single else list(texts)
        if not batch:
            return []
        encoded = self._tokenizer(batch, padding=True, truncation=True, return_tensors="pt")
        encoded = {key: value.to(self._device) for key, value in encoded.items()}
        with self._torch.no_grad():
            outputs = self._model(**encoded)
        sentence_embeddings = outputs.last_hidden_state[:, 0]
        if normalize_embeddings:
            sentence_embeddings = functional.normalize(sentence_embeddings, p=2, dim=1)
        vectors = sentence_embeddings.cpu().tolist()
        return vectors[0] if is_single else vectors


def is_meta_tensor_load_error(error: RuntimeError) -> bool:
    message = str(error).lower()
    return "meta tensor" in message and "to_empty" in message
