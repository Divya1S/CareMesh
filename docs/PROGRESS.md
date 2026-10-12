# Project History and Current State

The session memory for this repository. A new working session reads
`CLAUDE.md` first, then this file. It records what was built, in what
order, and what remains open; the other files under `docs/` describe the
system as it is.

## Current state

All phases of the build specification are complete, and a full codebase
audit (2026-10-12, recorded in `CODEBASE_AUDIT.md`) has been applied.
The gate at the end of the audit: 170 backend tests with an 80 percent
coverage floor (86 percent measured), mypy clean, 18 frontend tests, 23
eval cases, production dependency audits clean, and the browser journey
passing. Nothing is in flight; the working tree is committed.

## History

**2026-08-10, foundation and the vertical slice.** Phase 0 produced the
architecture proposal and ADRs 0001 to 0004 (Redpanda as the broker, the
fake LLM provider as the default, the outbox pattern, a small workflow
engine in the repository). The vertical slice followed in seven steps:
the compose stack, clean layer backend, Alembic migrations, auth with
rotating refresh tokens, and RBAC with resource level authorization
(S1); the Next.js student app on the design token system with generated
API types (S2); the transactional outbox, relay, and idempotent consumer
with dead letters (S3); the AI gateway with the prompt registry,
structured output validation, full request auditing, and the fake
provider with injectable failures (S4); Dira replies with visible
provenance (S5); the risk signal agent, deterministic escalation, the
review workflow, and the clinician queue (S6); the operations console,
the eval runner with a golden dataset, and the Playwright journey (S7).

**2026-08-10, broadening.** The RAG platform on pgvector with versioned
documents, lexical embeddings, tenant scoped retrieval, reranking, and
cited answers (ADR 0006); school referrals and the guardian portal with
least privilege by construction; payer eligibility checks behind a
labeled fake adapter and a claim state machine; Prometheus metrics with
a provisioned Grafana dashboard; the Dira safety and retrieval eval
suites; and security hardening with Redis rate limits, an append only
audit trail, `SECURITY.md`, and `THREAT_MODEL.md`.

**2026-08-11, upgrade plan and final review.** Documentation and CI;
agentic Dira with a bounded tool loop and SSE streaming (ADR 0007);
semantic embeddings through fastembed with a measured comparison against
the lexical default; a real Gemini adapter proven by an opt in live
check; an MCP server with two read only tools; a containerized backend,
a paper deployment design, and load numbers. The final six perspective
review (`FINAL_REVIEW.md`) found six high severity issues, all fixed and
re validated.

**2026-10-12, codebase audit.** An end to end audit found and fixed seven
critical and twelve high findings, each with a regression test, and an
independent review of those fixes found and corrected two more defects.
Highlights: the crisis phrase floor runs before the model call and opens
review on its own when the provider fails; Dira's memory reads the newest
messages; workflow transitions are compare and swap; refresh tokens live
in families with reuse detection; the audit logs use their own connection
pool; model calls never hold a database connection; streaming generates
each reply once with a faithful tool transcript; the API edge has an
explicit Redis failure policy, security headers, and correct status
codes; the gate gained type checking, a coverage floor, secret scanning,
a production build, and dependency audits. `CODEBASE_AUDIT.md` has the
full list and the remaining issues in priority order.

## Known limitations

- Frontend tokens live in localStorage; httpOnly cookies behind Next.js
  route handlers are the documented fix.
- Message creation has no idempotency key; a client retry after a network
  failure can duplicate a message and a model call.
- Lists paginate by offset.
- Audit rows for successful decisions are written before the business
  transaction commits.
- Evals run on the fake provider only; a labeled dataset and a real model
  run are the next step (`EVALUATION.md`).
- Five high severity npm advisories remain in `eslint-config-next`'s
  transitive lint tooling (dev only, no non major fix available).

## Next steps

A labeled risk dataset and a real model evaluation run, hybrid retrieval
(BM25 plus dense), a runtime output guardrail for Dira, httpOnly cookies,
and a public demo deployment on the fake provider.

## Standing constraints

- Zero budget: everything runs free and locally. Real LLM API calls are
  the only anticipated cost and stay off unless switched on by env var,
  flagged before use.
- The development machine is a laptop: Redpanda instead of Kafka, compose
  profiles, the observability stack off by default.
- Writing uses simple language with no em dashes and no dashes as
  punctuation. Commits carry no AI attribution.
- Dev workers run on the host (commands in `CLAUDE.md`) or in containers
  through the compose `app` profile. Run `./scripts/verify.sh` before
  declaring anything done.
