# PROGRESS

> Session memory for CareMesh AI. A fresh session must be able to resume from
> this file alone. Read `CLAUDE.md` first, then this file, before doing anything.

## Current phase

**S3, events online: COMPLETE. Gate passed on 2026-08-10.** Next phase is
**S4: the AI Gateway with the fake provider as the default.**
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

## In flight

- Nothing. S3 closed cleanly, working tree committed.

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

## Next steps (S4, AI Gateway)

1. `LLMProvider` protocol in the application layer; `FakeLLMProvider`
   (deterministic, scenario driven, `# SIMULATED`, injectable failures) as
   the default via `LLM_PROVIDER=fake` (ADR 0002).
2. Prompt registry with versioned prompts; structured output validation with
   bounded retry then typed error.
3. `AIRequest` / `AIResponse` tables and full request logging: model,
   provider, prompt version, tokens, cost, latency, validation result,
   simulated flag, correlation id.
4. A stub adapter test proving the env var provider swap (no real API calls,
   no keys, still zero cost).
5. Gate: gateway calls logged, validated, and labeled simulated end to end.

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
