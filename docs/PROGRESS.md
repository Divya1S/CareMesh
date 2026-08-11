# PROGRESS

> Session memory for CareMesh AI. A fresh session must be able to resume from
> this file alone. Read `CLAUDE.md` first, then this file, before doing anything.

## Current phase

**RAG (spec P6): COMPLETE. Gate passed on 2026-08-10** (83 backend tests,
13 frontend tests, 7/7 evals). The vertical slice S1 to S7 was completed
earlier the same day.

Next broadening candidates, pick with the human: school and guardian
surfaces (P9), payer workflows (P10), the observability compose profile,
eval expansion (add retrieval quality cases), security hardening.
Phase 0 was approved by the human on 2026-08-10 and the approved plan is
`docs/PHASE_0_PROPOSAL.md` (roadmap in section 11). All frontend work follows
`docs/DESIGN.md` (added by the human; authoritative).

## Done

- 2026-08-10, Phase 0: audit, proposal (all 12 sections), approval. ADRs 0001
  to 0004 recorded (Redpanda broker, fake LLM provider default, outbox
  pattern, workflow engine in the repo).
- 2026-08-10, S1 Foundation, all validated by `./scripts/verify.sh` (green):
  - `docker-compose.yml`: Postgres 16 (host port 5433, see gotchas in
    CLAUDE.md), Redis 7, Redpanda v24.2 in dev mode, all with healthchecks.
    A test database `caremesh_test` is created by an init script.
  - Backend in clean layers under `backend/app/`: `domain/` (entities, UUIDv7
    generator, zero framework imports), `application/` (ports, authorization
    policies, auth and conversation use cases), `infrastructure/` (SQLAlchemy
    models and repositories, Argon2 hashing, JWT service, structlog setup,
    settings), `api/` (thin routes, problem details errors, correlation ID
    middleware).
  - Alembic migration `e95545ccf66a`: organizations, users, auth_sessions,
    conversations, messages, care_assignments, with intentional indexes.
  - Auth: login, single use rotating refresh tokens backed by an
    auth_sessions table, `/api/v1/auth/me`. RBAC roles plus resource level
    policies: patients see only their own conversations, therapists only
    assigned patients, cross tenant access reads as 404, other roles denied.
  - API: `/api/v1/conversations` CRUD plus messages, paginated, all behind
    bearer auth. `/healthz` checks the database.
  - Tests: 32 passing (unit: ids, authorization policies, security; API
    integration against dockerized Postgres through the real migrations).
  - `backend/scripts/seed.py` (idempotent demo data,
    student@demo.caremesh.org / therapist / ops, password caremesh-demo),
    `backend/.env.example`, `scripts/verify.sh`.
  - Live smoke test performed: uvicorn on 8000, login, create conversation,
    post message, 401 without token.

- 2026-08-10, S2 student app, all validated by `./scripts/verify.sh` (green)
  and a Playwright browser smoke test (welcome, login, create conversation,
  send message, reload persists, crisis panel, zero console errors):
  - Next.js 16 app under `frontend/` with the DESIGN.md token system
    (`src/styles/tokens.css`, rose/gold palette, no blue, gold reserved for
    AI), fonts Sora / Plus Jakarta Sans / JetBrains Mono via next/font.
  - Core components on tokens: Button, Card, Chip, AIFrame (AI provenance
    wrapper with SIMULATED chip, built early per design), ChatBubble
    (patient/dira/clinician variants), EmptyState, Field.
  - Pages: lite welcome page (thread illustration, honesty banner), login,
    chat (left rail with disabled "soon" surfaces, conversation list, new
    conversation, composer, crisis resources panel always in the header).
  - API client with problem details parsing and automatic refresh token
    rotation retry; TypeScript API types generated from the backend OpenAPI
    schema (`scripts/gen-api-types.sh`, regenerate after API changes).
  - Backend: CORS for http://localhost:3000 via settings.
  - Frontend tests: vitest + testing library (9 tests: AIFrame provenance,
    ChatBubble labeling, token storage). verify.sh now runs frontend lint,
    typecheck, and tests. Playwright installed (dev dep) for smoke and later
    real E2E.

- 2026-08-10, S3 events online, validated by `./scripts/verify.sh` (36 backend
  tests green) and a live three process demo (API + relay + consumer: one
  request's correlation id observed across the outbox row, the relay publish
  log, and the consumer processed log):
  - Outbox `domain_event_log` and idempotency ledger `processed_events`
    (migration `cf719708a06e`). `PatientMessageCreated` v1 is written in the
    same transaction as the message insert; payloads carry ids only, never
    content. Documented in `docs/EVENTS.md`.
  - Relay worker (`app.workers.relay`): FOR UPDATE SKIP LOCKED batches,
    publishes to `caremesh.conversation.patient_message_created` keyed by
    organization id, marks `published_at`.
  - Consumer worker (`app.workers.conversation_consumer`, group
    `caremesh-conversation-worker`): envelope validation, exactly once
    effect via `processed_events`, bounded retries with backoff, dead
    letters to `<topic>.dlq`. S6 plugs risk analysis into this skeleton.
  - Integration tests cover: outbox written transactionally with the request
    correlation id, relay publish and mark, consumer idempotency
    (processed then duplicate), and a poison message landing on the DLQ.

- 2026-08-10, S4 AI Gateway, validated by `./scripts/verify.sh` (47 backend
  tests green):
  - `AIGateway` in the application layer: resolves versioned prompts from
    the registry (`dira_reply` v1, `risk_signal` v1), enforces a timeout,
    validates structured outputs against a Pydantic schema with one bounded
    retry then a typed `AIValidationError`, and logs **every** call
    (success, validation failure, timeout, provider error) to the
    `ai_requests` table (migration `20e15ec02c23`) with provider, model,
    prompt version, tokens, cost, latency, correlation id, and the
    simulated flag. The log writes in its own session so failures survive
    the caller's rollback.
  - `FakeLLMProvider` (`# SIMULATED`, ADR 0002): default via
    `LLM_PROVIDER=fake`. Deterministic keyword scenarios (crisis, low mood,
    exam stress, appointment, default), schema shaped risk JSON, zero cost,
    always `simulated=True`. Failure injection markers
    `[[fail:timeout]]`, `[[fail:malformed]]`, `[[fail:error]]`.
  - Provider factory: `fake` works, test proves a stub swap by name, and
    selecting anthropic/openai/gemini fails loudly with a clear message
    that real adapters arrive only when paid usage is switched on.
  - Tests: fake provider determinism and scenarios (unit), gateway logging
    of ok / validation_failed / timeout, structured output roundtrip,
    unknown prompt rejection (integration).

- 2026-08-10, S5 Dira minimal, validated by `./scripts/verify.sh` (52 backend
  and 11 frontend tests green) and a browser smoke test with a reviewed
  screenshot (gold Dira bubble, ✦ label, SIMULATED chip, zero console errors):
  - Patient messages get a Dira reply through the gateway (`dira_reply` v1,
    fake provider), generated synchronously in the request (ADR 0005) with
    the last 12 messages as conversation memory. Clinician messages get no
    reply. Gateway failures are swallowed after being audited in
    `ai_requests`, so Dira being down never blocks the patient's message
    (tested with the `[[fail:error]]` marker).
  - Messages carry AI provenance (`ai_request_id`, `simulated`, migration
    `7af8902c8905`) and the API exposes the simulated flag.
    `AIResponseGenerated` v1 goes to the outbox in the same transaction and
    is documented in `docs/EVENTS.md`.
  - Chat UI: Dira bubbles show the SIMULATED chip from the API flag, and the
    header carries the persistent disclosure that Dira is an AI companion,
    not a therapist.

- 2026-08-10, S6 risk signal and clinician review, validated by
  `./scripts/verify.sh` (64 backend and 13 frontend tests green) and a live
  four process browser demo (API, relay, consumer, frontend): a student's
  crisis message flowed through Redpanda into the Risk Signal agent, opened
  a workflow, appeared in the therapist's review queue in the gold AI frame
  with SIMULATED and severity labels, and was accepted with an audited
  resolution. Zero console errors.
  - Domain: `risk.py` (RiskSignal, RiskReview, deterministic
    `escalation_required`: self harm and crisis always escalate, severity 2
    and up escalates) and `workflows.py` (explicit state machine,
    `validate_transition`, append only history). Tables and migration
    `de7fe2fdc2ca`: risk_signals, risk_reviews (unique per signal),
    workflow_instances, workflow_transitions.
  - Consumer rework: idempotency mark and ALL effects (signal, workflow,
    outbox events) commit in one transaction, so retries and duplicates are
    safe; a failed analysis leaves no partial state (tested). Malformed AI
    output dead letters after bounded retries (tested).
  - Events: RiskSignalDetected, RiskReviewRequired, HumanReviewCompleted,
    documented in docs/EVENTS.md. Evidence text never enters payloads.
  - Review API: GET /api/v1/reviews (therapist, assigned patients only) and
    POST /api/v1/reviews/{workflow_id} (accept, edit with severity override,
    reject; terminal states refuse a second decision). Authorization tested:
    unassigned therapist empty and 403, patient 403.
  - Clinician UI at /clinician: queue items inside AIFrame with provenance,
    severity as icon plus text (SeverityLabel), accept / edit / reject with
    the frame transitioning to the rose approved state. Login now routes
    therapists to /clinician.

- 2026-08-10, S7 ops console, evals, and the E2E journey, closing the slice.
  Validated by `./scripts/verify.sh` (backend, frontend, and now evals) and
  `./scripts/e2e.sh` (real browser journey with reviewed screenshots):
  - Ops API under `/api/v1/ops` (ops_admin only, org scoped, tested):
    workflows with full transition history and state filter, AI request
    inspector (list plus detail with prompt messages and response), event
    outbox listing, safe event republish (clears published_at; consumers
    are idempotent so replays are safe, tested), and a DLQ viewer that
    reads the dead letter topic with a throwaway consumer group.
  - Ops console UI at `/ops`: dense light theme per DESIGN.md 4.7, status
    chips, mono ids, expandable workflow history and AI request detail,
    republish with a confirm dialog that explains idempotency, dead
    letters section. Ops admins land there after login.
  - Evals: `backend/evals/` golden dataset v1 (7 cases: normal, ambiguous,
    safety, prompt injection, malformed output) runs the real gateway and
    risk_signal prompt against the fake provider, checks classification
    AND the deterministic escalation decision, writes results with model
    and dataset versions, and fails verify.sh below 100 percent.
  - E2E: `frontend/e2e/journey.mjs` plus `scripts/e2e.sh` boot the full
    stack (API, relay, consumer, frontend), then drive student message,
    Dira reply, therapist accept, and ops visibility in headless Chromium.

- 2026-08-10, RAG (spec P6), validated by `./scripts/verify.sh` and a browser
  check of `/resources` with a reviewed screenshot (grounded answer in the
  AI frame with SIMULATED chip and a citations row; zero console errors):
  - Postgres swapped to the pgvector image (ADR 0006; one dev volume reset,
    recorded in gotchas). Migration `0a19fa7b0620`: documents (versioned by
    source_name, status lifecycle ingesting/ready/failed/superseded),
    document_chunks (vector(384), HNSW cosine index), rag_retrievals (the
    groundedness audit trail: what was retrieved, what was cited).
  - Real pipeline: normalize, paragraph chunking with overlap (unit
    tested), local lexical hashing embeddings (deterministic, normalized,
    related text ranks higher than unrelated, unit tested), tenant scoped
    cosine search, keyword overlap rerank, grounded generation through the
    `knowledge_answer` v1 prompt with schema validated citations.
  - Honest edges: unchanged content re-ingest is idempotent; changed
    content creates version N+1 and supersedes the old one; a question
    with no relevant sources declines without calling the LLM at all; org
    B cannot retrieve org A documents (all integration tested).
  - API `/api/v1/knowledge`: documents list (org members), ingest
    (ops_admin only), ask (grounded answer plus citations with used
    flags). Seed now ingests three fictional resource documents.
  - Student surface at `/resources`: ask box, answer in the AIFrame with
    the sources row (cited vs retrieved but not cited), library list.
    Resources is now a live link in the chat rail.

## In flight

- Nothing. The RAG phase closed cleanly, working tree committed.

## Known limitations (intentional, coming in later phases)

- No rate limiting yet (Redis is running but unused; first use will be
  documented per the conventions).
- No audit log table yet; no domain events published yet (S3 brings the
  outbox and Redpanda flow).
- Ops admin role exists but has no surface until the ops console phase.
- Frontend stores tokens in localStorage for now; the security hardening
  phase moves them to httpOnly cookies behind a route handler.
- Chat refreshes messages on send only; live updates (polling or SSE) come
  with Dira in S5.

## Next steps (broadening, pick with the human)

The proposal (section 11) sequences the rest as: deep RAG (spec P6),
deeper Dira and clinician workspace (P5/P8), school and guardian surfaces
(P9), payer workflows (P10), full ops and the observability compose
profile (P11/P12), eval expansion (P13), security hardening (P14),
performance (P15), deployment docs (P16), final review (P17). Reasonable
defaults if the human just says continue: RAG next (it deepens Dira with
grounded answers and citations), then school and guardian.

## Notes for the next session

- Dev workers run on the host (relay, conversation consumer commands are in
  CLAUDE.md). Containerizing api plus workers behind a compose profile is
  deferred to the hardening phases; the proposal wanted compose processes,
  and this deviation is recorded here on purpose.

## Standing constraints from the human (2026-08-10)

- **Zero budget:** everything must run free and locally. Flag it explicitly
  before any external or paid service is ever needed. Real LLM API calls are
  the only anticipated exception and stay off unless switched on by env var.
- The machine may struggle with heavy services, so Redpanda instead of Kafka,
  compose profiles, and the observability stack off by default.
- **Writing rules:** commits must never carry Claude attribution of any kind,
  so Claude never appears as a contributor on GitHub. All writing uses simple
  language with no em dashes and no dashes as punctuation.
