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

- **Phase:** security hardening (spec P14) complete (gate passed 2026-08-10). Next candidates: deployment docs (P16), final Staff Engineer review (P17)
- **Security:** Redis rate limiting (login per address and account, AI endpoints per user; Redis's one documented use), append only `audit_logs` for login success and failure (masked emails), review decisions, claim decisions, and event republishes. `docs/SECURITY.md` (controls and honest gaps) and `docs/THREAT_MODEL.md` (threats, mitigations, failure modes). Note: the test suite raises LOGIN_ATTEMPTS_PER_MINUTE via env in conftest because fixtures log in constantly
- **Evals:** three suites in `backend/evals/` (risk golden-v1 with escalation precision and recall, dira-v1 safety property checks, retrieval-v1 hit@k and MRR over real pgvector in a throwaway org), all gated at 100 percent in verify.sh via `--dataset all`. See `docs/EVALUATION.md`
- **Observability:** `/metrics` on the API (HTTP, AI, workflow, outbox metrics; DB backed gauges refresh every 15s), Prometheus + Grafana provisioned dashboard behind `docker compose --profile observability up -d`. See `docs/OBSERVABILITY.md` for the catalog and what is deferred (worker metrics, tracing, alerting)
- **P10:** eligibility checks go through the labeled `fake-payer-1` adapter (`# SIMULATED`, `app/infrastructure/payer/`); therapists submit claims for assigned patients at `/billing` (requires a passing check); payer staff review at `/payer` with required denial reasons, resubmission, and the full transition history rail. Claim states: submitted, approved, denied, resubmitted. Demo account payer@demo.caremesh.org
- **P9:** school staff see a names only roster and submit referrals (real workflow: submitted, accepted, declined); accepting assigns the therapist and notifies linked guardians. Guardians see only explicitly shared items (guardian_links gates everything): care updates written for them, notifications, resources. Surfaces at `/school` and `/guardian`; demo accounts school@ and guardian@demo.caremesh.org
- **RAG:** real pipeline (ADR 0006): versioned documents chunked and embedded (local lexical hashing, EMBEDDING_PROVIDER env var) into pgvector, tenant scoped cosine search plus keyword rerank, grounded answers with citations through the `knowledge_answer` prompt, retrieval trail in `rag_retrievals`. API under `/api/v1/knowledge`; student surface at `/resources`; ingestion is ops_admin only
- **Ops console:** `/ops` (ops_admin): workflows with transition history, AI request inspector, event outbox with safe republish (idempotent consumers), DLQ viewer. Evals: `backend/evals/` golden dataset runs in verify.sh; E2E journey: `./scripts/e2e.sh`
- **Risk flow:** the conversation consumer runs the Risk Signal agent (gateway, `risk_signal` v1) on patient messages; deterministic thresholds in `domain/risk.py` open a Risk Escalation workflow; therapists review at `/clinician` with accept, edit, or reject; everything is evented and the workflow history is append only
- **Dira:** patient messages get a synchronous reply through the gateway (ADR 0005), persisted as a `dira` message with `ai_request_id` and `simulated` provenance columns, `AIResponseGenerated` emitted to the outbox, SIMULATED chip rendered in the chat
- **AI:** all LLM calls go through `AIGateway` (`app/application/ai/gateway.py`): prompt registry with versions, structured output validation with bounded retry, timeout, and every call logged to `ai_requests` with the simulated flag. Provider chosen by `LLM_PROVIDER` env var; `fake` is the default (deterministic scenarios, `# SIMULATED`, injectable failures via `[[fail:timeout|malformed|error]]` markers)
- **Events:** outbox in `domain_event_log`, relay worker, idempotent consumer with DLQ. See `docs/EVENTS.md`. Workers run on the host in dev: `uv run python -m app.workers.relay` and `uv run python -m app.workers.conversation_consumer`
- **Approved through:** Phase 0 was explicitly approved by the human on 2026-08-10 ("start")
- **Working end to end:** compose stack (Postgres 5433, Redis, Redpanda), auth with JWT and rotating refresh tokens, RBAC plus resource level authorization, conversation and message CRUD, and the Next.js student app (welcome, login, chat) styled per `docs/DESIGN.md` with OpenAPI generated types. Backend 32 tests plus frontend 9 tests green through `./scripts/verify.sh`; browser flow smoke tested with Playwright
- **Design:** `docs/DESIGN.md` is the authoritative design reference for all frontend work. Tokens live in `frontend/src/styles/tokens.css`. Gold is reserved for AI provenance; no blue anywhere
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
backend/          FastAPI app (api/ application/ domain/ infrastructure/ workers/ evals/)
frontend/         Next.js app (src/app src/components src/lib e2e/)
docs/             BUILD_SPEC.md, PROGRESS.md, PHASE_0_PROPOSAL.md, DESIGN.md, EVENTS.md, adr/
docker/           postgres init scripts (compose file lives at the repo root)
scripts/          verify.sh (phase gate), e2e.sh (browser journey), gen-api-types.sh, seed via backend/scripts
```

## Commands

```bash
# Full local stack
docker compose up -d
# Observability (Prometheus 9090, Grafana 3001), off by default
docker compose --profile observability up -d

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
uv run python -m evals.run --dataset all

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
- Postgres runs the pgvector/pgvector:pg16 image (RAG, ADR 0006). The swap from alpine required one dev volume reset; if the volume ever predates the swap, drop it and reseed.
- The ORM has no relationship() mappings, so parent rows must be flushed before children insert in the same transaction (documents before chunks, organizations before users). See tests/conftest.py and SqlDocumentRepository.add.

## Session protocol

1. Read this file, then `docs/PROGRESS.md`.
2. Confirm the current phase and its exit criteria before writing code.
3. Work in small validated increments; run relevant tests as you go.
4. Before ending: commit, run `./scripts/verify.sh` if code changed, update `docs/PROGRESS.md` (and this file if architecture, conventions, or commands changed).
5. Never skip a phase gate or start a new phase without the approval noted in "Current state".
