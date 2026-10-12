# CODEBASE AUDIT

Audit started 2026-10-12 against commit 2004569. Scope: the whole
repository, read end to end, with the full gate run first as a baseline
(118 backend tests, 13 frontend tests, 23 eval cases, all green). This
document records what the system is, where the risk sits, and every
finding with its status. The companion report of what changed is at the
end of this file.

## Architecture in one page

Three backend processes from one image: the FastAPI API, the outbox relay,
and the conversation consumer. Infrastructure: PostgreSQL 16 with pgvector,
Redis (rate limits only), Redpanda (Kafka API). A Next.js App Router
frontend, all client components, talks to the API over HTTP and SSE. An
MCP server (stdio) exposes two read only tools.

Backend layers under `backend/app/`:

| Layer | Holds | Depends on |
|---|---|---|
| `domain/` | entities, risk policy and crisis floor, workflow state machines, chunking, UUIDv7, event constructors | standard library only |
| `application/` | use case services, authorization policies, ports (Protocols), the AI gateway, prompt registry, tool abstraction | domain |
| `infrastructure/` | SQLAlchemy models and repositories, Argon2 and JWT, Redis limiter, Kafka wrappers, LLM and embedding providers, fake payer, metrics, settings | application, domain |
| `api/` | thin routes, Pydantic schemas, dependency wiring, correlation id middleware, problem details errors | all |

Composition is in `api/deps.py`. One `AsyncSession` per request commits on
success and rolls back on any exception. Repositories share it, so a use
case is one transaction. Two writers escape it on purpose and use their
own session: the AI request log and the audit log.

## The critical workflow

1. `POST /conversations/{id}/messages/stream`: rate limit check, user
   lookup, authorization, message insert plus `PatientMessageCreated`
   outbox row, commit before the first SSE byte.
2. `stream_dira_reply`: last 12 messages as history, crisis phrase check
   decides whether Dira gets tools, gateway runs bounded tool rounds and
   streams the text, reply persisted with `ai_request_id` and `simulated`.
3. Relay: `FOR UPDATE SKIP LOCKED` batch of unpublished rows, publish keyed
   by organization, mark published.
4. Consumer: envelope validation, idempotency mark (`processed_events`,
   `ON CONFLICT DO NOTHING`), risk classification through the gateway with
   a schema, deterministic escalation, workflow plus events, one commit.
5. Therapist reviews at `/reviews`, decides, and the decision is a new
   row, a transition, an audit entry, and an event.

## Highest risk areas (before fixes)

1. **The safety backstop depended on the model.** The deterministic
   crisis phrase floor in `analyze_message` ran after the gateway call.
   A provider outage, timeout, or malformed output meant no escalation at
   all, not even for an explicit crisis phrase, and the event dead
   lettered with no alert.
2. **Lost updates on workflow state.** Every transition was read, check,
   write with no lock and no conditional update. Two concurrent decisions
   on the same review produced an `IntegrityError` and a 500; on claims,
   referrals, and appointments both would have written.
3. **A silent drop path in the consumer.** If publishing to the dead
   letter topic failed, the loop moved on and the next offset commit
   skipped that record permanently.
4. **Pool self deadlock.** Audit and AI log writes took a second
   connection from the same pool while the request held its first. Fifteen
   concurrent chat requests could wait each other out to the pool timeout.
5. **Stale context for Dira.** History loaded the first 100 messages and
   kept the last 12 of those, so conversations past 100 messages never
   showed Dira (or the crisis tool guard) the newest message.
6. **Model calls inside open transactions** in the non streaming message
   endpoint and in the consumer.

## Findings

Severity: Critical (safety, data integrity, crash), High (broken behavior
under realistic conditions), Medium (quality, resilience, hygiene), Low
(nice to have). Status is updated as work lands.

| ID | Sev | Finding | Where | Status |
|---|---|---|---|---|
| C1 | Critical | Crisis phrase floor evaluated after the model call; provider failure disables escalation | `use_cases/risk_analysis.py` | fixed |
| C2 | Critical | Dira history loads first 100 messages then slices the last 12; stale after message 100 | `use_cases/conversations.py`, repositories | fixed |
| C3 | Critical | DLQ publish failure skips the record; next commit drops it for good | `workers/conversation_consumer.py` | fixed |
| C4 | Critical | Workflow transitions are check then act; races give 500 or double writes; `ConflictError` never raised | repositories, reviews, claims, referrals, appointments | fixed |
| C5 | Critical | Client token refresh has no single flight; parallel 401s log the user out | `frontend/src/lib/api.ts` | fixed |
| C6 | Critical | Audit and AI log writers borrow a second connection from the request pool; deadlock under load | `api/deps.py`, `main.py`, workers | fixed |
| C7 | Critical | `next` 16.3.0 carries critical advisories; `pyjwt` 2.13.0 carries three; both have non major fixes | `frontend/package.json`, `backend/pyproject.toml` | fixed |
| H1 | High | Streaming generates the final answer twice; a streamed function call yields empty text and an error | `ai/gateway.py`, providers | fixed |
| H2 | High | LLM calls inside open database transactions (plain message endpoint, consumer) | routes, consumer | fixed |
| H3 | High | Gateway errors are not mapped; knowledge `ask` returns 500 on provider failure | `api/problems.py` | fixed |
| H4 | High | Redis outage turns rate limited routes into 500s; no fail open or closed policy | `infrastructure/rate_limit.py`, deps, auth route | fixed |
| H5 | High | Refresh tokens: no reuse detection, unconditional revoke allows a double refresh, refresh endpoint unlimited | `use_cases/auth.py`, repositories, migration | fixed |
| H6 | High | Review queue is N plus 1; no index on `workflow_instances.subject_id` or `appointment_requests.conversation_id` | repositories, migration | fixed |
| H7 | High | `request_appointment` idempotency is check then insert with no lock | repositories | fixed |
| H8 | High | Gemini adapter ignores `finishReason`, no retry on 429 and 5xx, new client per call, tool id equals tool name | `infrastructure/ai/gemini_provider.py` | fixed |
| H9 | High | Tool loop: arguments not validated, extra calls dropped silently, assistant tool call turn missing from transcript | `ai/gateway.py`, `ai/types.py` | fixed |
| H10 | High | `prompt_version=1` hard coded on risk signals | `use_cases/risk_analysis.py`, `ai/types.py` | fixed |
| H11 | High | Chunker can emit a chunk larger than `max_chars` when a long paragraph follows a partial chunk | `domain/knowledge.py` | fixed |
| H12 | High | Streaming audit row records `ok` when the client disconnects before the reply persists | `ai/gateway.py` | fixed |
| M1 | Medium | Provider, embedder, and gateway constructed per request; Gemini opens a client per call | `api/deps.py` | fixed |
| M2 | Medium | No type checking, coverage, secret scanning, or dependency audit in CI | `ci.yml`, `pyproject.toml` | fixed |
| M3 | Medium | Login limiter uses the socket address; behind a proxy every user shares one bucket | `api/routes/auth.py`, settings | fixed |
| M4 | Medium | No security headers on API responses; `/metrics` is public | `api/middleware.py` | fixed |
| M5 | Medium | Stream path has no 401 refresh and no abort on unmount; two inputs lack accessible labels; resources page has no error state | frontend | fixed |
| M6 | Medium | Docs overstate code: refresh replay in THREAT_MODEL, ADR 0004 retries and timeouts, ADR 0005 not superseded, ADR 0007 provider enforced guard, stale PROGRESS limitations | docs | fixed |
| M7 | Medium | `/healthz` ignores Redis; pool sizing not configurable | `api/routes/health.py`, `infrastructure/db.py`, settings | fixed |
| M8 | Medium | vitest 3.x and eslint-config-next carry dev only advisories | `frontend/package.json` | partly fixed |
| M9 | Medium | JWT has no issuer or audience claims | `infrastructure/security.py` | fixed |
| L1 | Low | No `Idempotency-Key` on message creation; a client retry duplicates the message and the model call | routes | open |
| L2 | Low | Offset pagination on all lists; deep pages scan | repositories, routes | open, documented |
| L3 | Low | Audit row for a decision is written before the business transaction commits | audit log design | open, documented |
| L4 | Low | Dummy hash timing equalization is not pinned by a test | `use_cases/auth.py` | open, measured by hand |

Verified non issues worth recording: the dummy Argon2 hash does equalize
login timing (29.4 ms unknown email versus 28.9 ms wrong password,
measured); secrets are not in git history; the Gemini key travels in a
header, not the URL; events carry ids only; logs never carry content;
problem details never echo request bodies.


## What changed

Fourteen commits between 2004569 and the end of the audit, each with a
regression test, each run through the full gate before the next. In
severity order:

**Safety.** The crisis phrase floor is evaluated before the model is
called (`RiskClassifier.classify`), and when the provider fails on a
message that matched the floor, the consumer records a floor only signal
(model `crisis-phrase-floor`, severity 3, no `ai_request_id`; migration
d744ccf51ef9) and opens the review workflow anyway. A provider outage
can no longer silence an explicit disclosure. Tests: provider down with
a crisis phrase (review opens, failure audited), provider down without
one (dead letters with no partial state), model under classifying
(floor escalates anyway).

**Data integrity and concurrency.** Workflow transitions are compare and
swap; the loser of a race gets a 409 and no audit row, and a refused
state machine move is a 409 instead of an unhandled exception. Refresh
tokens live in families with reuse detection and a conditional revoke
(migration ededa2e5230b). `request_appointment` takes an advisory lock
before its one open request check. The consumer seeks back when a dead
letter publish fails instead of committing past the record. Tests:
concurrent decisions, concurrent refreshes, concurrent appointment asks,
reuse revoking the thief's chain, a held record on a broken producer.

**Resource behavior.** The audit and AI request logs write through their
own pool (a test shows the same pool deadlocking on one connection and
the separate pool succeeding). Provider, embedder, and gateway are built
once per process. Both reply paths and the consumer release the database
connection before calling the model (a probe provider counts idle in
transaction sessions during the call: zero). The review queue is one
query, and the two missing indexes exist (migration 601c3bf9590b).

**The AI gateway.** One tool loop serves `complete()` and
`stream_reply()`; streaming rounds stream from the first provider call,
so a reply is generated once (a counting provider proves one call
without tools, two with one tool round, and never a non streaming call).
Tool arguments are validated against the declared schema, the model's
own call turn stays in the transcript, over budget calls are reported
back, a validation retry carries the error, a disconnecting client is
audited as `cancelled`, and a failed mutating tool as `provider_error`.
Dira's memory loads the newest twelve messages. The Gemini adapter keeps
one pooled client, retries 429 and 5xx with jitter, raises on a safety
block, reports `MAX_TOKENS`, and sends grouped function responses under
the model's real call turn.

**The API edge.** Redis outages fail login closed (503, Retry-After) and
AI endpoints open, counted and logged. Model failures are 502 and 504.
Refresh shares the login address bucket. Proxy aware client address
behind `TRUST_PROXY_HEADERS`. Security headers on every API response.
`/healthz` reports Redis as degraded; `/metrics` takes a bearer token.
JWTs carry and verify issuer and audience; weak secrets are refused
outside dev. Citations only for chunk ids the model was offered.

**Frontend.** Single flight token refresh (parallel 401s no longer log
the user out), refresh and abort on the stream path, error states on
chat and resources, accessible labels on two inputs, newest page of
messages. next 16.4.0, vitest 4.1.11, eslint-config-next 16.4.0;
`.npmrc` pins legacy peer resolution around an npm 10.9 bug.

**Engineering rigor.** mypy (clean), a coverage floor (80, measured 86),
gitleaks, a production build, pip-audit and npm audit in CI, Dependabot.
pyjwt, httpx2, and urllib3 upgraded past published advisories. Docs corrected where they claimed
more than the code: THREAT_MODEL's refresh replay row, ADRs 0004, 0005,
0007, PROGRESS's stale limitations.

## Verification at the end of the audit

| Check | Result |
|---|---|
| `./scripts/verify.sh` | all checks passed |
| Backend tests | 162 passed (118 at the start) |
| Backend coverage | 85.9 percent, floor 80 |
| mypy | no issues in 69 files |
| Frontend lint, typecheck, tests | clean, 17 passed (13 at the start) |
| Frontend production build | succeeds |
| Evals | risk 7/7, dira 9/9, retrieval 7/7 |
| `npm audit --omit=dev` | 0 vulnerabilities |
| `npm audit` (dev included) | 5 high in eslint-config-next's transitive tooling, no non major fix |
| pip-audit on production dependencies | clean after upgrading pyjwt, httpx2, and urllib3 |
| Browser journey `./scripts/e2e.sh` | passed: student, Dira, risk, review, ops, in headless Chromium |
| Live model check | not run; it costs nothing on the free tier but the audit stayed offline by design |

## Remaining issues, in priority order

1. **No idempotency key on message creation (L1).** A client retry after
   a network failure creates a duplicate message, event, and model call.
   Fix: an `Idempotency-Key` header stored with a unique constraint per
   user, returning the original response on replay.
2. **No runtime output guardrail on Dira.** The banned phrase properties
   exist only in the eval suite. With a real provider, add a moderation
   pass and the same checks at runtime with a safe fallback reply.
3. **Evals run on the fake provider only.** The harness is real, the
   quality signal is not. A labeled dataset and a real model run are the
   next step (docs/EVALUATION.md).
4. **Plaintext AI transcripts in `ai_requests`.** Reads are audited;
   encryption, redaction, and retention are not implemented.
5. **Tokens in localStorage.** The documented fix is httpOnly cookies
   behind Next.js route handlers.
6. **Audit rows for successful decisions commit before the business
   transaction (L3).** Deliberate for failures, imperfect for successes;
   writing success audits through the outbox would close it.
7. **Offset pagination (L2).** Keyset pagination on UUIDv7 ids is a small
   change when lists grow.
8. **Dev only npm advisories** in eslint-config-next's transitive tooling;
   revisit when a 16.x release pulls the fixed micromatch chain.
9. **No worker metrics, tracing, or alert rules** (docs/OBSERVABILITY.md).
   DLQ depth should page someone in a real deployment.
10. **Tenant isolation by query scoping, not row level security.**

## Production readiness assessment

This remains a portfolio simulation and must not be used with real
patients; nothing below changes that.

| Dimension | Assessment | Evidence |
|---|---|---|
| Functional correctness | Good for the implemented scope | 162 tests against real infrastructure; every audit finding has a regression test; the e2e journey |
| Security | Good controls for a demo, documented gaps for a real deployment | Token families, CAS transitions, explicit limiter policy, headers, scanning in CI; localStorage tokens, no RLS, plaintext transcripts remain |
| Test coverage | Good | 86 percent line coverage with a floor; concurrency and failure paths tested; frontend page logic still lightly tested |
| Maintainability | Good | Clean layers, mypy clean, one tool loop instead of two, docs that match the code |
| Performance | Adequate at demo scale, untested beyond a laptop | Model calls hold no connection, queue is one query, indexes added; no load test against a real provider |
| Accessibility | Reasonable | Labels on every control, visible focus, alerts for errors; no automated audit run |
| Deployment readiness | Not deployed; paper design | Containers and compose profile exist; DEPLOYMENT.md lists what a real deployment still needs |

Confidence: high on correctness within the tested paths, because every
claim above is backed by a test run in this audit; medium on behavior
under real provider latency and real load, which was not exercised.
