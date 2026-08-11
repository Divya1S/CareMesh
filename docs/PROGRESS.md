# PROGRESS

> Session memory for CareMesh AI. A fresh session must be able to resume from
> this file alone. Read `CLAUDE.md` first, then this file, before doing anything.

## Current phase

**S2, student app: COMPLETE. Gate passed on 2026-08-10.** Next phase is
**S3: events online (outbox table, relay, Redpanda consumer worker, DLQ).**
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

## In flight

- Nothing. S2 closed cleanly, working tree committed.

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

## Next steps (S3, events online)

1. `DomainEventLog` outbox table plus migration (envelope: event id, type,
   schema version, occurred at, correlation and causation ids, tenant id,
   payload, published at).
2. Emit `PatientMessageCreated` in the same transaction as message writes.
3. Relay process publishing outbox rows to Redpanda
   (`caremesh.conversation.patient_message_created`), aiokafka producer.
4. Worker consumer with idempotency (processed events table), bounded
   retries, and a dead letter topic; runs as a separate compose process.
5. Tests: outbox write is transactional, relay publishes, consumer is
   idempotent, poison messages land in the DLQ. Gate: event flow
   demonstrable end to end, failure and replay paths tested.

## Standing constraints from the human (2026-08-10)

- **Zero budget:** everything must run free and locally. Flag it explicitly
  before any external or paid service is ever needed. Real LLM API calls are
  the only anticipated exception and stay off unless switched on by env var.
- The machine may struggle with heavy services, so Redpanda instead of Kafka,
  compose profiles, and the observability stack off by default.
- **Writing rules:** commits must never carry Claude attribution of any kind,
  so Claude never appears as a contributor on GitHub. All writing uses simple
  language with no em dashes and no dashes as punctuation.
