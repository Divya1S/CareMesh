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
    # Blended score below which retrieval declines to answer. Absolute
    # similarity thresholds do NOT transfer between embedding spaces:
    # lexical cosine sits near zero for unrelated text, dense models sit
    # near 0.3. Each provider carries its own measured cutoff.
    min_answer_score: float

    def embed(self, texts: list[str]) -> list[list[float]]: ...


def _bucket(token: str) -> tuple[int, float]:
    digest = hashlib.md5(token.encode()).digest()
    index = int.from_bytes(digest[:4], "big") % EMBEDDING_DIM
    sign = 1.0 if digest[4] % 2 == 0 else -1.0
    return index, sign


class LocalLexicalEmbedding:
    name = "local-lexical-v1"
    dim = EMBEDDING_DIM
    min_answer_score = 0.05

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


class FastembedEmbedding:
    """Real semantic embeddings, free and local: BAAI/bge-small-en-v1.5
    through fastembed (ONNX, no torch). First use downloads the model
    (about 90MB, approved); afterwards it runs fully offline. 384
    dimensions, matching the pgvector column."""

    name = "fastembed-bge-small-en-v1.5"
    dim = EMBEDDING_DIM
    # Measured on the eval corpus: true matches score 0.42 and up, off
    # domain queries top out near 0.32 (blended cosine plus keyword score).
    min_answer_score = 0.38

    def __init__(self) -> None:
        from fastembed import TextEmbedding  # imported lazily: heavy

        self._model = TextEmbedding("BAAI/bge-small-en-v1.5")

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [vector.tolist() for vector in self._model.embed(texts)]


def create_embedding_provider(name: str) -> EmbeddingProvider:
    if name == "local_lexical":
        return LocalLexicalEmbedding()
    if name == "fastembed":
        return FastembedEmbedding()
    raise RuntimeError(
        f"Unknown EMBEDDING_PROVIDER: {name}. Use local_lexical (default, "
        "no downloads) or fastembed (semantic, one time model download)."
    )
