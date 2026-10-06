"""Pluggable text embedding providers.

* ``fastembed`` – local ONNX model (default ``BAAI/bge-small-en-v1.5``), no API key, runs on CPU.
* ``openai``    – any OpenAI-compatible ``/embeddings`` endpoint.
* ``hash``      – deterministic feature hashing; zero downloads, used by tests and CI.

All providers return L2-normalised float32 vectors of exactly ``settings.embedding_dim`` dimensions,
so cosine similarity is a dot product and the pgvector column type never changes.
"""

import hashlib
import logging
import math
import threading
from collections import Counter
from itertools import pairwise
from typing import Protocol

import numpy as np

from app.core.config import Settings
from app.core.errors import ConfigurationError
from app.services.text_utils import cjk_bigrams, tokenize

logger = logging.getLogger(__name__)


class EmbeddingProvider(Protocol):
    name: str
    model: str
    dim: int
    # Cosine similarity below which the best match is considered "probably not relevant".
    min_relevance: float

    def embed_documents(self, texts: list[str]) -> np.ndarray: ...

    def embed_query(self, text: str) -> np.ndarray: ...


def _normalize_rows(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return (matrix / norms).astype(np.float32)


class HashEmbeddingProvider:
    """Signed feature hashing over stemmed unigrams + bigrams. Lexical, but fast and fully deterministic."""

    name = "hash"
    min_relevance = 0.12

    def __init__(self, dim: int):
        self.dim = dim
        self.model = f"feature-hash-{dim}"

    def _vector(self, text: str) -> np.ndarray:
        tokens = tokenize(text)
        features = tokens + [f"{a}_{b}" for a, b in pairwise(tokens)] + cjk_bigrams(tokens)
        vec = np.zeros(self.dim, dtype=np.float32)
        for feature, count in Counter(features).items():
            digest = int.from_bytes(hashlib.blake2b(feature.encode(), digest_size=8).digest(), "little")
            sign = 1.0 if digest >> 63 else -1.0
            vec[digest % self.dim] += sign * (1.0 + math.log(count))
        return vec

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        return _normalize_rows(np.stack([self._vector(t) for t in texts]))

    def embed_query(self, text: str) -> np.ndarray:
        return self.embed_documents([text])[0]


class FastEmbedProvider:
    name = "fastembed"
    min_relevance = 0.55  # bge-style models compress cosine scores into a high, narrow band

    def __init__(self, settings: Settings):
        self.model = settings.embedding_model
        self.dim = settings.embedding_dim
        self.batch_size = settings.embedding_batch_size
        self.cache_dir = settings.model_cache_dir
        self._engine = None
        self._lock = threading.Lock()

    def _load(self):
        if self._engine is None:
            with self._lock:
                if self._engine is None:
                    from fastembed import TextEmbedding

                    logger.info("Loading embedding model %s (first run downloads it)…", self.model)
                    self.cache_dir.mkdir(parents=True, exist_ok=True)
                    try:
                        self._engine = TextEmbedding(model_name=self.model, cache_dir=str(self.cache_dir))
                    except Exception as exc:
                        raise ConfigurationError(f"Could not load embedding model '{self.model}': {exc}") from exc
        return self._engine

    def _check(self, matrix: np.ndarray) -> np.ndarray:
        if matrix.shape[1] != self.dim:
            raise ConfigurationError(
                f"Embedding model '{self.model}' produces {matrix.shape[1]}-d vectors but EMBEDDING_DIM={self.dim}."
            )
        return _normalize_rows(matrix)

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        vectors = list(self._load().passage_embed(texts, batch_size=self.batch_size))
        return self._check(np.stack(vectors))

    def embed_query(self, text: str) -> np.ndarray:
        vector = next(iter(self._load().query_embed(text)))
        return self._check(np.asarray([vector]))[0]


class OpenAIEmbeddingProvider:
    name = "openai"
    min_relevance = 0.25

    def __init__(self, settings: Settings):
        if not settings.openai_api_key:
            raise ConfigurationError("EMBEDDING_PROVIDER=openai requires OPENAI_API_KEY.")
        from openai import OpenAI

        self.client = OpenAI(
            api_key=settings.openai_api_key, base_url=settings.openai_base_url, timeout=settings.llm_timeout_seconds
        )
        self.model = settings.embedding_model
        self.dim = settings.embedding_dim
        self.batch_size = max(settings.embedding_batch_size, 64)

    def _embed(self, texts: list[str]) -> np.ndarray:
        import openai

        rows: list[list[float]] = []
        # text-embedding-3-* can shorten vectors server-side to match the pgvector column.
        extra = {"dimensions": self.dim} if self.model.startswith("text-embedding-3") else {}
        for start in range(0, len(texts), self.batch_size):
            batch = texts[start : start + self.batch_size]
            try:
                response = self.client.embeddings.create(model=self.model, input=batch, **extra)
            except openai.APIError as exc:
                raise ConfigurationError(f"Embedding request failed: {exc}") from exc
            rows.extend(item.embedding for item in sorted(response.data, key=lambda d: d.index))
        matrix = np.asarray(rows, dtype=np.float32)
        if matrix.shape[1] != self.dim:
            raise ConfigurationError(
                f"Embedding model '{self.model}' returned {matrix.shape[1]}-d vectors but EMBEDDING_DIM={self.dim}."
            )
        return _normalize_rows(matrix)

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        return self._embed(texts)

    def embed_query(self, text: str) -> np.ndarray:
        return self._embed([text])[0]


def build_embedding_provider(settings: Settings) -> EmbeddingProvider:
    if settings.embedding_provider == "hash":
        return HashEmbeddingProvider(settings.embedding_dim)
    if settings.embedding_provider == "openai":
        return OpenAIEmbeddingProvider(settings)
    return FastEmbedProvider(settings)
