"""Embedding providers for RAG (ADR 0006).

The default is a real, free, deterministic LOCAL LEXICAL embedding: the
classic hashing trick over word unigrams and bigrams, tf weighted and L2
normalized. Cosine similarity over these vectors is genuine lexical
similarity, so retrieval is real information retrieval, not a mock. It is
not semantic: paraphrases with no shared vocabulary will not match.
Replacement path: implement a semantic EmbeddingProvider (local model or
paid API) and select it by the EMBEDDING_PROVIDER env var; dimensions and
interface stay the same.
"""

import hashlib
import math
import re
from itertools import pairwise
from typing import Protocol

EMBEDDING_DIM = 384

_WORD = re.compile(r"[a-z0-9']+")


class EmbeddingProvider(Protocol):
    name: str
    dim: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


def _bucket(token: str) -> tuple[int, float]:
    digest = hashlib.md5(token.encode()).digest()
    index = int.from_bytes(digest[:4], "big") % EMBEDDING_DIM
    sign = 1.0 if digest[4] % 2 == 0 else -1.0
    return index, sign


class LocalLexicalEmbedding:
    name = "local-lexical-v1"
    dim = EMBEDDING_DIM

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        words = _WORD.findall(text.lower())
        vector = [0.0] * EMBEDDING_DIM
        tokens = words + [f"{a}_{b}" for a, b in pairwise(words)]
        for token in tokens:
            index, sign = _bucket(token)
            vector[index] += sign
        norm = math.sqrt(sum(v * v for v in vector))
        if norm == 0:
            return vector
        return [v / norm for v in vector]


def create_embedding_provider(name: str) -> EmbeddingProvider:
    if name == "local_lexical":
        return LocalLexicalEmbedding()
    raise RuntimeError(
        f"Unknown EMBEDDING_PROVIDER: {name}. Semantic providers land when "
        "they are deliberately switched on; dev runs on local_lexical."
    )
