# CLAUDE.md: CareMesh AI

> This file is Claude's persistent memory for this repository. Read it at the start of every session, **then read `docs/PROGRESS.md`** before doing anything else. Keep both files accurate. Future sessions depend on them, not on conversation history.

## What this project is

CareMesh AI is a **portfolio project** simulating an AI native youth mental health platform. Full specification: `docs/BUILD_SPEC.md` (the v2 build spec). It is **not a real healthcare product**.

Honesty rules that must never be broken (repeated here because they carry weight):
- Never claim HIPAA compliance, clinical validity, or readiness for real patients, anywhere, including README copy and UI text.
- Never present mocks, hardcoded AI output, or static dashboards as real. Mocks live behind interfaces, are clearly labeled `# SIMULATED`, and have a documented replacement path.
- Never report anything complete without running its validation. Docs describe reality only.
- Dira is not a therapist. AI suggestions never silently become clinician decisions.

## Current state

- **Phase:** S1, Foundation, complete (gate passed 2026-08-10). Next: S2, conversation API polish plus the student UI
- **Approved through:** Phase 0 was explicitly approved by the human on 2026-08-10 ("start")
- **Working end to end:** compose stack (Postgres 5433, Redis, Redpanda), auth with JWT and rotating refresh tokens, RBAC plus resource level authorization, conversation and message CRUD, 32 tests green through `./scripts/verify.sh`
- **Priority path:** vertical slice first (Student, Dira, risk signal, clinician workspace, ops console) before broadening to the school, guardian, and payer surfaces. See roadmap S1 to S7 in the proposal, section 11
- **Key decisions, approved with Phase 0 and recorded as ADRs 0001 to 0004:** Redpanda as the broker speaking the Kafka API, the fake LLM provider as the dev default with real providers switched on only by the `LLM_PROVIDER` env var, the outbox pattern for events, and a small workflow engine inside the repo
- **Budget constraint, standing:** everything free and local. Real LLM API usage is the only permitted future cost and must be flagged to the human before use

## Architecture summary

- Backend: Python + FastAPI, clean architecture (`api/ → application/ → domain/ → infrastructure/`). No business logic in route handlers.
- Frontend: Next.js + TypeScript, App Router. One design system; every AI generated element is visibly labeled.
- Data: PostgreSQL (source of truth, Alembic migrations), Redis (caching, rate limits, and locks only, each use documented), Redpanda for domain events with dead letter queues.
- AI: all LLM calls go through the AI Gateway (`LLMProvider` abstraction). No direct provider SDK calls from business logic. Every request logged with model, prompt version, tokens, cost, latency, validation result.
- Workflows: explicit state machines with audit history; inspectable from the ops console. No business critical logic in anonymous background tasks.

## Repository layout

```
backend/          FastAPI app (api/ application/ domain/ infrastructure/)
frontend/         Next.js app
docs/             BUILD_SPEC.md, PROGRESS.md, PHASE_0_PROPOSAL.md, ARCHITECTURE.md, adr/, ...
docker/           compose files, service configs
scripts/          dev + validation scripts
evals/            golden datasets, evaluation runner
```

## Commands

```bash
# Full local stack
docker compose up -d

# Backend
cd backend && uv sync                     # or: pip install -e ".[dev]"
uv run pytest                             # all tests
uv run pytest tests/integration -m integration
uv run ruff check . && uv run ruff format --check .
uv run alembic upgrade head               # migrations

# Frontend
cd frontend && npm install
npm run dev
npm run lint && npm run typecheck
npm run test

# Evals
uv run python -m evals.run --dataset golden

# Phase exit check (run before declaring any phase complete)
./scripts/verify.sh
```

## Conventions

- **Python:** ruff (lint + format), full type hints, Pydantic v2 models at boundaries. Domain layer has zero framework imports.
- **TypeScript:** strict mode, no `any` without a comment justifying it. API types generated from OpenAPI, never hand duplicated.
- **Naming:** domain events are `PascalCase` facts in the past tense (`RiskSignalDetected`); Kafka topics follow `caremesh.<domain>.<event>` with versioned schemas.
- **IDs:** UUIDv7 primary keys; every request, workflow, and AI call carries a correlation ID.
- **Auth:** authorization enforced in the application layer, at the resource level, least privilege. Never rely on frontend hiding alone.
- **Errors:** consistent problem details error responses; no bare 500s for expected failures.
- **Git:** conventional commits (`feat:`, `fix:`, `docs:`, `refactor:`, `test:`); commit each coherent increment; never end a session with a broken repo (if unavoidable, record it in PROGRESS.md).
- **Attribution:** never add Claude attribution of any kind to commits, PR bodies, or docs. No Co-Authored-By trailers. Claude must not appear as a contributor on GitHub.
- **Writing style:** simple language everywhere (docs, commits, UI copy). No em dashes and no dashes used as punctuation. Hyphens stay only where syntax requires them: file names, URLs, CLI flags, and code identifiers.
- **Decisions:** every significant choice, including defaults chosen without asking, gets an ADR in `docs/adr/` (`NNNN-title.md`).
- **Secrets:** `.env` (gitignored) + `.env.example` kept current. Never commit keys. Never log message content, tokens, or fields that look like PII.

## Gotchas

- A Homebrew postgresql@16 on this machine owns 127.0.0.1:5432, so the compose Postgres publishes on host port 5433. All connection strings use 5433.
- pydantic EmailStr (email-validator) rejects reserved TLDs such as .test and .local. Demo and test accounts use @something.caremesh.org addresses.
- The ORM models define no relationship() mappings, so SQLAlchemy does not order inserts across tables for foreign keys in one flush. When seeding related rows in one session, flush per dependency level (see tests/conftest.py).
- The docker/postgres/init scripts (test database creation) only run on first container start. If the postgres volume predates a new init script, create the database manually or remove the volume.

## Session protocol

1. Read this file, then `docs/PROGRESS.md`.
2. Confirm the current phase and its exit criteria before writing code.
3. Work in small validated increments; run relevant tests as you go.
4. Before ending: commit, run `./scripts/verify.sh` if code changed, update `docs/PROGRESS.md` (and this file if architecture, conventions, or commands changed).
5. Never skip a phase gate or start a new phase without the approval noted in "Current state".
