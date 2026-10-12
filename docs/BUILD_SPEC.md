# Build Specification

The requirements the project was built against. This document defines
scope and standards; the other files under `docs/` describe what exists.

## Purpose

CareMesh AI is a portfolio project that simulates the engineering scope of
an AI native youth mental health platform. It is not a real healthcare
product.

Rules that hold everywhere in the repository:

- Never claim HIPAA compliance, clinical validity, or readiness for real
  patient care. The README and `SECURITY.md` state that this is a
  simulation and list what a real deployment would need.
- Never present mocked integrations, hard coded AI responses, or static
  dashboards as real functionality. Mocks are allowed only behind an
  interface, labeled as simulations, and documented with a replacement
  path.
- Documentation describes what exists, never aspirational functionality
  written as if implemented.
- Nothing is reported complete without validation that was executed. If
  something cannot be verified, say so.

Priorities, in order: correctness, safety, maintainability, reliability,
observability, security, testability, product usefulness, scalability. A
small number of well engineered systems is preferred over many shallow
features.

## Product scope

Ten surfaces: the student app, the guardian portal, the clinician
workspace, the school dashboard, the payer dashboard, the AI companion
(Dira), the operations console, the AI platform layer, the event driven
workflow infrastructure, and the observability and evaluation platform.

These are not ten separate dashboards. Everything is organized around one
workflow: a student reports a concern, Dira responds safely, risk signals
are detected and structured, deterministic logic decides what happens,
the therapist is notified when appropriate, a human reviews when
required, guardian and school workflows run when authorized, appointment
and payer workflows progress, domain events are emitted, and operations
can observe and audit every step.

Deterministic software is used wherever it is safer, simpler, or more
reliable than a model. AI is used, and measured, only where it adds
something a rule cannot.

Dira is not a therapist and never presents itself as a clinician or an
autonomous decision maker. Its functions: supportive companion, care
navigation, grounded information (RAG), structured assessment, risk
signal detection, appointment assistance, therapist handoff, escalation,
tool calling, structured outputs, and conversation memory.

The backend and every UI keep these distinct: AI generated information,
AI detected signals, AI recommendations, clinician decisions, system
actions, and human approved actions. An AI suggestion never silently
becomes a clinician decision.

## Architecture requirements

**Stack.** Python and FastAPI in clean layers (API, application, domain,
infrastructure) with no business logic in route handlers. Next.js with
TypeScript, one design system, loading, error, and empty states, clear
permission boundaries, and unmistakable AI labeling. PostgreSQL as the
primary store; Redis only where justified (caching, rate limits, locks)
and documented per use; a Kafka compatible broker. Docker Compose for the
full local stack. Cloud cost near zero, with any production mapping kept
clearly separate from what is deployed.

**AI gateway.** One centralized path to any model behind an
`LLMProvider` abstraction: prompt versioning, structured outputs with
validation, tool calling, retries, timeouts, rate limiting, request
tracing, and evaluation hooks. Every request records model, prompt
version, tokens, cost, latency, validation result, tool usage, and
outcome.

**Agents.** Specialize only where it brings a real benefit; prefer
deterministic orchestration with specialized model calls over open ended
agent conversations. Every agent defines its responsibility, schemas,
tools, permissions, failure behavior, evaluation criteria, and human
escalation behavior.

**Events.** Versioned schemas, producers and consumer groups,
idempotency, retries, dead letters, correlation and causation ids, and
documented purpose, payload, and failure behavior per event.

**Workflows.** Explicit orchestration for long running processes with
visible state transitions, human in the loop steps, failure recovery,
idempotency, audit history, and execution state inspectable from the
operations console. No business critical logic hidden in anonymous
background tasks.

**RAG.** A real pipeline: ingestion, normalization, chunking, embeddings,
vector storage, tenant filtering, retrieval, reranking, and grounded
generation with citations, with document versioning and a stored
retrieval trail. Dumping documents into a prompt does not count.

**Database.** A schema designed around access patterns, with migrations,
intentional indexes, constraints, clear transaction boundaries, tenant
isolation, and auditability.

**API.** OpenAPI, request and response validation, pagination, consistent
errors, and authorization at the correct layer.

**Payer system.** Simplified but real workflow engineering: eligibility,
claim submission and status, denial tracking, and resubmission, as state
machines emitting events, with external payer integrations mocked behind
labeled adapters.

**Operations console.** An engineering control plane: inspect workflows,
AI requests, escalations, the review queue, and dead letters; replay
events safely.

## Safety and security

Safety is architectural: input and output checks, risk signal detection,
escalation workflows, human review, audit logging, data minimization, and
explicit AI limitations. No autonomous emergency intervention; high risk
scenarios route to human escalation and crisis resources. The system never
diagnoses, prescribes, or makes clinical decisions on its own.
Deliverables: a safety architecture description, a threat model, a
failure mode analysis, and safety evaluation cases.

Security: authentication, RBAC plus resource level authorization, tenant
isolation, secrets management, input validation, rate limiting, and audit
logging. Least privilege everywhere: schools and guardians see only what
they are explicitly authorized to see.

## Observability and evaluation

Structured logging without sensitive data, metrics, correlation ids
across requests, events, and AI calls, and dashboards that are
actionable.

Evaluation is a subsystem, not an opinion. Golden datasets cover normal,
ambiguous, and safety sensitive conversations as well as hallucination,
retrieval failure, tool failure, prompt injection, malformed output, and
adversarial cases. Results are stored with model, prompt version, dataset
version, metrics, and failures, and regression tests surface degradation
when a model or prompt changes. Clinician accept, edit, and reject
decisions are captured as structured events that feed evaluation.

## Testing

Unit tests for domain logic, integration tests against Postgres, Redis,
the broker, and the AI gateway, API tests for critical endpoints,
workflow tests for success and failure paths, AI evaluation suites, and
end to end tests for critical journeys. Coverage is measured by
behavior, not by count; every important failure mode gets a test.

## Delivery process

Each feature follows the same loop: understand, inspect existing code,
design, identify failure modes, implement the smallest coherent
increment, test, self review, fix, document, and report what changed.
After each phase, a review from six perspectives (software engineering,
AI engineering, security, reliability, product, healthcare platform
architecture) looks for shallow implementations, fake AI, race
conditions, missing idempotency or authorization, weak observability,
prompt injection exposure, untested failure modes, and misleading
documentation. Problems found are fixed and re validated.

Tradeoffs are recorded as ADRs under `docs/adr/`, including defaults
chosen without asking. Project state lives in the repository: `CLAUDE.md`
holds the architecture summary, conventions, commands, and gotchas, and
`docs/PROGRESS.md` holds the project history and current state.

## Phases

Built in order, each closed by a phase gate: what was implemented, tests
executed with results, known limitations, review findings and fixes, and
the commands that must pass.

| Phase | Scope |
|---|---|
| 0 | Repository audit and architecture proposal, approved before any code |
| 1 | Core domain model, PostgreSQL, auth, RBAC |
| 2 | Backend APIs, patient and therapist workflows |
| 3 | Event driven infrastructure |
| 4 | AI gateway |
| 5 | Dira companion |
| 6 | RAG and knowledge platform |
| 7 | Risk detection and human escalation workflows |
| 8 | Clinician workspace |
| 9 | School and guardian workflows |
| 10 | Payer workflows |
| 11 | Operations control plane |
| 12 | Observability |
| 13 | AI evaluation framework |
| 14 | Security hardening |
| 15 | Testing and performance testing |
| 16 | Deployment and infrastructure |
| 17 | Final engineering review |

## Acceptance

Complete only when the architecture is coherent, the core workflows run
end to end, AI is integrated with explicit boundaries, RAG is real, event
driven workflows recover from failure, idempotency and authorization are
enforced, observability and evaluation exist with regression tests,
critical workflows are tested, security controls are implemented, the
documentation matches the code, local development is reproducible, and
the final review has been performed.
