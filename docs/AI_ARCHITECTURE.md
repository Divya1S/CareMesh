# AI ARCHITECTURE

## The gateway is the only path to a model

`app/application/ai/gateway.py`. Business logic depends on an `LLMProvider`
protocol, never a vendor SDK. The gateway owns:

- **Prompt registry** (`prompts.py`): named, versioned prompts. Unknown
  prompts are refused; every audit row records the version used.
- **Structured outputs:** a Pydantic schema per call, validated with one
  bounded retry, then a typed `AIValidationError`. Never silent
  acceptance, never silent dropping.
- **Timeouts** and typed failures (`AITimeoutError`, `AIProviderError`).
- **Auditing:** every call, success or failure, writes an `ai_requests`
  row (provider, model, prompt version, tokens, cost, latency, status,
  validation result, simulated flag, correlation id) in its own
  transaction so failures survive rollbacks. Prometheus counters increment
  in the same code path.

## Providers

Selected by `LLM_PROVIDER` (ADR 0002). The default `fake` provider is a
deterministic, clearly labeled simulation: scenario driven replies, schema
shaped structured outputs, injectable failure modes
(`[[fail:timeout|malformed|error]]`), zero cost, `simulated=True` on every
response. The simulated flag flows from the provider through the audit log
and the API to a visible badge on every AI element. Real adapters plug in
behind the same interface and are the only thing in the project that can
cost money.

## Agents (deterministic orchestration, specialized calls)

- **Conversation (Dira):** replies to patient messages with recent history
  as context (`dira_reply` v1). Not a therapist, says so persistently, and
  a gateway failure never blocks the patient's message.
- **Risk Signal:** runs in the event consumer on patient messages
  (`risk_signal` v1, schema validated). It produces a structured signal;
  it never decides. `escalation_required` in `app/domain/risk.py` is
  deterministic, unit tested code, and it opens the human review workflow.
- **Knowledge:** grounded answers over retrieved chunks
  (`knowledge_answer` v1) with citations; declines without calling the
  model when nothing relevant is retrieved.

## RAG pipeline

Ingestion (normalize, chunk with overlap, embed, version by source name,
supersede old versions) into pgvector; retrieval is tenant scoped cosine
search plus a keyword overlap rerank; answers cite chunks, and every
question stores its retrieval trail in `rag_retrievals` (what was fetched,
what was cited). Embeddings default to local lexical hashing (real lexical
retrieval, free, honest about not being semantic); providers swap by
`EMBEDDING_PROVIDER` (ADR 0006).

## Safety posture

The system never diagnoses, never prescribes, and never lets an AI
suggestion silently become a clinician decision: accept, edit, and reject
are explicit audited acts that resolve a workflow. Crisis category signals
always escalate regardless of severity score. Safety properties of Dira's
replies and injection resistance are regression tested in the eval suites
(docs/EVALUATION.md).
