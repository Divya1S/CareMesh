# ADR 0006: pgvector for vector storage, local lexical embeddings by default

Status: accepted (default chosen during the RAG phase, 2026-08-10)

## Context

The spec requires genuine RAG: chunking, embeddings, vector storage, tenant
filtered retrieval, reranking, and grounded generation with citations. No
fake RAG. The budget is zero and the machine is a laptop, which rules out
paid embedding APIs and makes heavy local models (torch based) unattractive.

## Decision

Two parts:

1. **Vector storage: pgvector** inside the existing Postgres (image swapped
   to pgvector/pgvector:pg16). Real cosine similarity search with an HNSW
   index, tenant scoped in SQL, no extra service on the laptop.
2. **Embeddings: local lexical hashing by default** (`local-lexical-v1`):
   the classic hashing trick over word unigrams and bigrams, tf weighted,
   L2 normalized, 384 dimensions, deterministic, standard library only.
   Cosine over these vectors is real lexical similarity, so retrieval is
   genuine information retrieval. It is NOT semantic: paraphrases without
   shared vocabulary will not match. Providers are selected by the
   EMBEDDING_PROVIDER env var behind an EmbeddingProvider interface,
   mirroring the LLM provider pattern (ADR 0002).

## Alternatives considered

- sentence-transformers locally: real semantic embeddings, free, but pulls
  torch (hundreds of MB) onto a laptop that is already running the full
  stack. Deferred, not rejected; it slots in behind the same interface.
- Paid embedding APIs: violates the zero budget constraint; opt in later.
- Random or hash-of-whole-text vectors: would be fake RAG. Rejected.

## Consequences

- Retrieval quality is honest but lexical; the docs and this ADR say so
  plainly, and retrieval quality metrics land with the eval expansion phase.
- Swapping in a semantic provider later changes one env var and requires a
  re-ingest (embedding dimensions may change: new migration at that point).

## Update (2026-08-11)

A real semantic provider landed: `EMBEDDING_PROVIDER=fastembed` runs
BAAI/bge-small-en-v1.5 locally through ONNX (one time ~90MB download, then
offline; 384 dimensions, so no schema change). Chunks record which
provider embedded them and similarity search filters to the querying
provider's vectors, because mixing embedding spaces produces garbage.
Each provider carries its own measured no answer threshold; the measured
comparison (lexical hit@1 0.5 vs semantic 1.0 on the eval suite, off
domain refusal preserved for both) lives in docs/EVALUATION.md.
`scripts/reingest.py` re-embeds stored chunks after a switch. The lexical
default remains for tests and CI: free, instant, no downloads.
- The dev Postgres volume was reset once for the image swap (alpine to the
  pgvector debian build); seed data recreates everything.
