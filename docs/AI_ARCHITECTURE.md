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

`LLM_PROVIDER=gemini` selects the real Gemini adapter
(`infrastructure/ai/gemini_provider.py`): plain httpx against the REST
API, no vendor SDK, mapping completions, structured JSON output, tool
calls, and SSE streaming onto the same request and response types the
fake provider uses. It needs `LLM_API_KEY` (free tier works) and defaults
to the `gemini-flash-latest` alias so provider model retirements do not
break it. `scripts/live_check.py` is the opt in proof that a real model
flows through the gateway with `simulated=false`; it never runs in
verify.sh or CI. Anthropic and OpenAI adapters would follow the same
shape but have no free tier; an Ollama adapter for local models is the
documented next free provider.

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
always escalate regardless of severity score, and a deterministic crisis
phrase floor in `domain/risk.py` forces escalation even when a model
(real, or steered by the message itself) under classifies. Crisis
precedence over tools is structural, not a prompt hope: the application
layer offers Dira zero tools on a turn whose latest patient message
contains crisis language, so no provider can detour a crisis disclosure
into a search or an appointment. The gateway also bounds tool use (three
rounds, one executed call per round) and aborts the reply if a mutating
tool fails mid write. Safety properties of Dira's replies and injection
resistance are regression tested in the eval suites (docs/EVALUATION.md);
those run on the deterministic fake provider and pin the prompt and the
structural guards, not a real model's judgment.
