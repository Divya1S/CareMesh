# PROGRESS

> Session memory for CareMesh AI. A fresh session must be able to resume from
> this file alone. Read `CLAUDE.md` first, then this file, before doing anything.

## Current phase

**S1, Foundation: COMPLETE. Gate passed on 2026-08-10.** Next phase is
**S2: conversation API polish plus the minimal Next.js student app.**
Phase 0 was approved by the human on 2026-08-10 and the approved plan is
`docs/PHASE_0_PROPOSAL.md` (roadmap in section 11).

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

## In flight

- Nothing. S1 closed cleanly, working tree committed.

## Known limitations (intentional, coming in later phases)

- No rate limiting yet (Redis is running but unused; first use will be
  documented per the conventions).
- No audit log table yet; no domain events published yet (S3 brings the
  outbox and Redpanda flow).
- Ops admin role exists but has no surface until the ops console phase.
- No frontend yet (S2).

## Next steps (S2)

1. Minimal Next.js student app under `frontend/`: login, conversation list,
   chat view, design system foundations, AI labeling components ready for S5.
2. OpenAPI generated TypeScript types (no hand duplicated API types).
3. Frontend lint, typecheck, and tests wired into `scripts/verify.sh`.
4. S2 gate: a student logs in, sends a message, sees it persisted.

## Standing constraints from the human (2026-08-10)

- **Zero budget:** everything must run free and locally. Flag it explicitly
  before any external or paid service is ever needed. Real LLM API calls are
  the only anticipated exception and stay off unless switched on by env var.
- The machine may struggle with heavy services, so Redpanda instead of Kafka,
  compose profiles, and the observability stack off by default.
- **Writing rules:** commits must never carry Claude attribution of any kind,
  so Claude never appears as a contributor on GitHub. All writing uses simple
  language with no em dashes and no dashes as punctuation.
