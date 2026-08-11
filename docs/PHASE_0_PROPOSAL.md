# CareMesh AI. Phase 0: Repository Audit and Architecture Proposal

> **Status:** AWAITING HUMAN APPROVAL. No implementation code has been written.
> Per `docs/BUILD_SPEC.md`, Phase 1 must not begin until this proposal is explicitly approved.
>
> **Reality note:** CareMesh AI is a portfolio project that simulates an AI native
> youth mental health platform. It is not a real healthcare product. It is not HIPAA
> compliant, has no clinical validity, and must never be used with real patients.

---

## 1. Repository Assessment

The audit was performed rather than assumed. Findings:

| Aspect | Finding |
|---|---|
| Files present | `CLAUDE.md` (project memory) and the build spec, now at `docs/BUILD_SPEC.md` |
| Code | None. No backend, frontend, tests, migrations, or scripts |
| Build and env config | None. No docker, no dependency manifests, no CI |
| Git history | None. The folder was not a git repository until this session, so `git init` was performed |
| Technical debt and security issues | None possible, since nothing exists |
| Documentation quality | The two existing docs are accurate and current |

What to preserve, change, remove, and add:

| Action | Item | Rationale |
|---|---|---|
| Preserve | `CLAUDE.md` conventions and honesty rules | They are the project contract. Everything below follows them |
| Change | Spec location, moved to `docs/BUILD_SPEC.md` | Canonical docs location per the repo layout |
| Remove | Nothing | Nothing to remove |
| Add | Everything else | Greenfield build per the roadmap in section 11 |

Because this is a greenfield start there are no legacy constraints, but there is
also no working reference. Every phase gate must therefore prove that its
increment runs end to end instead of leaning on past behavior.

---

## 2. Product Architecture

There are ten surfaces: student app, guardian portal, clinician workspace,
school dashboard, payer dashboard, Dira, ops console, AI platform, event
infrastructure, and the observability and evaluation platform. They are
organized around one canonical workflow, not ten disconnected dashboards:

> Student reports concern, Dira interacts safely, risk signals are detected,
> structured risk info is generated, deterministic workflow logic evaluates it,
> a workflow is triggered, the therapist is notified when appropriate, context
> is summarized, humans review when required, guardian and school workflows run
> when authorized, appointment and care workflows progress, payer workflows
> update, domain events are emitted, operations can monitor, and every
> important action is observable and auditable.

Product principles that bind every surface:

1. **AI provenance is visible everywhere.** Every UI element distinguishes
   between AI generated information, AI detected signals, AI recommendations,
   clinician decisions, system actions, and human approved actions. An AI
   suggestion never silently becomes a clinician decision. Acceptance is an
   explicit, audited act.
2. **Dira is not a therapist.** She is a supportive companion, care navigator,
   information assistant grounded in RAG, and a runner of structured
   assessments. High risk content routes to human escalation and emergency
   resource workflows, never to autonomous intervention.
3. **Deterministic where safer.** Risk classification thresholds, escalation
   routing, and workflow transitions are deterministic code. AI produces
   structured signals and summaries that feed that code. It does not drive it.
4. **The vertical slice defines the product until it works end to end:**
   Student, Dira, risk signal, clinician workspace, ops console. School,
   guardian, and payer surfaces are deferred on purpose (section 11).

---

## 3. System Architecture

**Everything in local dev runs at zero cost.** All services are open source and
run in Docker Compose. The only potential cost in the entire project is
optional use of real LLM APIs, which is off by default (section 6).

Layers, from top to bottom:

- **Frontend:** Next.js with TypeScript and the App Router. Student app,
  clinician workspace, and ops console first. School, guardian, and payer
  surfaces come later. All calls go over HTTP with types generated from OpenAPI.
- **Backend:** FastAPI with clean architecture.
  - `api/` holds thin route handlers: validation and auth context only, no business logic.
  - `application/` holds use cases, authorization at the resource level, and workflow orchestration.
  - `domain/` holds entities, value objects, state machines, and events, with zero framework imports.
  - `infrastructure/` holds Postgres repositories, Redis, broker producers and consumers, and the AI Gateway providers.
- **Data:** PostgreSQL as the source of truth with Alembic migrations. Redis
  only for caching, rate limits, and locks, with each use documented.
- **Events:** Redpanda speaking the Kafka API (section 5), with worker
  processes consuming domain events.
- **AI:** the AI Gateway behind an `LLMProvider` abstraction, with the provider
  chosen by env var: fake, anthropic, openai, or gemini (section 6).

Key decisions, each stated as decision, alternatives, reason, and consequence:

- **A monolith with clean internal boundaries, not microservices.**
  Alternatives: one service per surface, or a modular monolith with separately
  deployed workers. Reason: one developer and one laptop. The boundaries live
  in the package structure and the event schemas, which is where the
  engineering signal is. Consequence: extraction later stays possible because
  domain events and schemas are versioned from the start, and the compose file
  already runs the API and the workers as separate processes of the same codebase.
- **Workers run as separate compose processes** consuming from Redpanda, so
  async behavior (retries, dead letter queues, consumer groups) is real rather
  than an in process shortcut.
- **Docker Compose profiles** named `core` and `observability`, so the laptop
  only runs what the current work needs.
- **Package management:** uv for Python and npm for the frontend. Both free.
- Terraform plus a GCP production architecture stays a paper design only. It is
  documented but never deployed, so cloud cost stays zero.

---

## 4. Domain Model

Entities per the spec, designed around access patterns. The detailed schema is
Phase 1 work. This is the shape and the decisions that carry weight:

- **Identity and tenancy:** `Organization` is the tenant root. `User` is the
  auth identity, with role links to `Patient`, `Guardian`, `Therapist`,
  `SchoolStaff`, and `PayerStaff`. Every clinical row carries
  `organization_id`. Tenant isolation is enforced in the application layer on
  every query, not by convention.
- **Conversation core:** `Conversation` and `Message`. The sender is typed as
  patient, dira, clinician, or system, so provenance is a column, not a habit.
- **Risk and care:** `RiskSignal` is structured: category, severity,
  confidence, evidence spans, and the model and prompt version that produced
  it. It is never a diagnosis. `RiskReview` is the human decision record.
  `CarePlan` and `Appointment` complete the care path.
- **Workflow and events:** `WorkflowInstance` with type, state, state history,
  and a correlation ID. `DomainEventLog` is an append only outbox (section 5).
  `AuditLog` is append only: actor, action, resource, and before and after references.
- **AI:** `AIRequest` and `AIResponse` with model, provider, prompt version,
  tokens, cost, latency, validation result, and a `simulated` boolean.
  `PromptVersion`, `Evaluation`, and `EvaluationRun` support the eval system.
- **Knowledge and payer, in deferred phases:** `Document`, `DocumentChunk`,
  `Claim`, `EligibilityCheck`, `AuthorizationRequest`.

Choices that cut across the model:

- UUIDv7 primary keys, which are ordered by time and friendly to indexes. This
  is already a spec convention.
- Soft deletion only where the domain needs it, such as patient facing content.
  Audit, event, and AI request tables are append only and never deleted.
- Access patterns drive indexes. The clinician review queue by severity, the
  conversation timeline, workflows by state, and AI spend by day all get
  intentional indexes in Phase 1. Nothing speculative.

---

## 5. Event Architecture

### Broker choice: Redpanda recommended over Apache Kafka

| Criterion | Apache Kafka | Redpanda |
|---|---|---|
| Laptop footprint | JVM plus controller, typically 1 to 2 GB of RAM or more, slow cold start | Single native binary, runs comfortably in roughly 256 to 512 MB in dev mode |
| Local dev setup | Multiple compose services, tuning needed | One container, with a dev mode made for this |
| Protocol | Kafka | Compatible with the Kafka API, same wire protocol |
| Client code | aiokafka and standard Kafka clients | Identical: same aiokafka code, same topics, same consumer groups |
| Tooling | CLI scripts and JVM tools | rpk, one excellent CLI, plus an optional console UI |
| Cost | Free (Apache 2.0) | Free for this use (source available BSL, unrestricted for dev and self hosted use) |
| Resume value | The canonical name | Kafka compatible is standard industry phrasing and the skills transfer one to one |

**Decision: Redpanda.** Reason: your machine may struggle with full Kafka, and
Redpanda gives the identical programming model (topics, partitions, consumer
groups, offsets, dead letter queues) at a fraction of the resource cost.
Consequence: zero lock in. Because the wire protocol and client libraries are
the same, swapping to real Kafka is a compose file change, and everything
built and learned transfers. Alternative rejected: Redis Streams. It is lighter
still, but it is a different model and would undercut the spec requirement of a
realistic broker.

### Event design

- **Topics** follow `caremesh.<domain>.<event>`, for example
  `caremesh.risk.risk_signal_detected`, with versioned JSON schemas defined in
  Pydantic, exported as JSON Schema, and a `schema_version` in every envelope.
- **Envelope fields:** `event_id` (UUIDv7), `event_type`, `schema_version`,
  `occurred_at`, `correlation_id`, `causation_id`, `tenant_id`, `payload`.
- **Outbox pattern:** domain events are written to `DomainEventLog` in the same
  Postgres transaction as the state change, and a relay publishes them to
  Redpanda. Reason: no dual write inconsistency, and events can be replayed
  from the outbox.
- **Consumers** are idempotent by `event_id` through a processed events table,
  retry with backoff a bounded number of times, and then send to a dead letter
  topic per source topic. Dead letters are inspectable and retryable from the
  ops console.
- **Initial events for the vertical slice:** `PatientMessageCreated`,
  `AIResponseGenerated`, `RiskSignalDetected`, `RiskReviewRequired`,
  `HumanReviewCompleted`, `WorkflowFailed`. The rest, such as the appointment,
  guardian, and insurance events, arrive with their phases. Each event is
  documented in `docs/EVENTS.md` with purpose, producer, consumers, payload,
  version, and its retry, idempotency, and failure behavior.
- Async only where it earns its keep: risk analysis, notifications, and
  projections. Plain synchronous calls serve simple reads and writes.

---

## 6. AI Architecture

### The AI Gateway is the only path to any LLM

Business logic depends on an `LLMProvider` interface, never on a provider SDK.

```python
class LLMProvider(Protocol):
    async def complete(self, req: LLMRequest) -> LLMResponse: ...
    # LLMRequest: messages, prompt reference (name and version), tool
    #             definitions, response schema, budget hints, correlation_id
    # LLMResponse: text or structured output, tool calls, token usage,
    #              cost, latency, simulated: bool
```

Gateway responsibilities: provider routing, a prompt registry with versioning,
validation of structured outputs (Pydantic, with a bounded retry on failure and
then a typed error, never a silent pass), the tool calling protocol, timeouts
and retries and fallbacks, rate limiting, response caching where safe, safety
checks before and after the model call, and full logging of every request into
`AIRequest` and `AIResponse`: model, prompt version, workflow, agent, tokens,
cost, latency, validation result, tool usage, retries, and the simulated flag.

### Fake provider first, by design, because of the budget constraint

- `LLM_PROVIDER=fake` is the **default**. The `FakeLLMProvider` is:
  - **Clearly labeled.** Every response carries `simulated: true`, is logged as
    simulated, and renders in every UI with a visible SIMULATED badge. The code
    is marked `# SIMULATED` and documents its replacement path. It is never
    presented as real AI.
  - **Scenario driven, not random.** Deterministic fixture responses are keyed
    by prompt name and matched conversation scenario (greeting, sadness
    disclosure, self harm disclosure, appointment request, and so on), so risk
    workflows, evals, and end to end tests are reproducible and free.
  - **Contract complete.** It emits structured outputs against the same
    schemas, simulated tool calls, fake token and cost figures, and injectable
    failure modes (timeout, malformed output, refusal), so the retry and
    fallback paths can be genuinely tested.
- Setting `LLM_PROVIDER` to anthropic, openai, or gemini swaps in a real
  adapter through env vars (`LLM_API_KEY`, with the model pinned by config).
  **This is the single element of the project that could cost money.** It stays
  off unless you turn it on, and I will flag it loudly whenever a phase would
  benefit from real model runs. Free tiers, for example Gemini, can be tried
  first when that moment comes.

### Agents

Deterministic orchestration plus specialized AI calls. No agent to agent chat.
The initial roster is below. Each agent defines its responsibility, input and
output schemas, tools, permissions, failure behavior, and eval criteria. Any
agent that cannot justify itself gets cut.

| Agent | In the slice? | Responsibility |
|---|---|---|
| Conversation (Dira) | Yes | Safe supportive replies, tool calls, handoff proposals |
| Risk Signal | Yes | Structured risk signals from messages, never diagnoses |
| Clinical Context | Yes, minimal | Conversation summaries for clinician review |
| Knowledge (RAG) | Later | Grounded answers with citations, in the RAG phase |
| Care Coordination, Operations, Documentation | Later | Added only when their phase shows a real need |

---

## 7. Workflow Architecture

Explicit, inspectable state machines. No business critical logic in anonymous
background tasks.

- **Engine:** a small workflow engine inside the repo, built on Postgres:
  `WorkflowInstance` plus transition functions plus event triggers.
  Alternatives: Temporal, which is heavy for a laptop and hides the state
  machine engineering this project is meant to demonstrate, and Celery chains,
  which are opaque and keep no audit history. Reason: the spec wants visible
  state transitions, compensation, and audit history as first class
  engineering. Consequence: we own the retry and timeout logic, which is
  exactly the portfolio signal.
- Each workflow type declares its states, allowed transitions, side effects,
  retry and timeout policy per step, compensation, and its human review gates.
- Transitions are recorded append only with state history, actor, reason, and
  correlation ID. They are visible in the ops console, and stuck or failed
  workflows can be retried or resolved there.
- **First workflow, for the vertical slice: Risk Escalation.**
  `PatientMessageCreated`, then risk analysis, then classification against
  deterministic thresholds. Below the threshold: log and continue. Above it:
  `RiskReviewRequired`, then clinician review (accept, edit, or reject, all
  audited), then notification and resolution. Failure paths are included and
  tested: AI timeout, malformed output, and reviewer timeout leading to escalation.

---

## 8. Security Model

- **Authentication:** email plus Argon2 password hashing, short lived JWT
  access tokens, and rotating refresh tokens. Standard free libraries.
- **Authorization:** RBAC with the roles patient, guardian, therapist,
  school staff, payer staff, and ops admin, **plus resource level checks in the
  application layer**. Every use case answers whether this actor may act on
  this resource. A therapist reads only assigned patients. Guardians and
  schools see only what they are explicitly authorized to see. Hiding things in
  the frontend is never the control.
- **Tenant isolation:** `organization_id` scoping enforced centrally in
  repositories and use cases. Cross tenant access is a tested failure case.
- **Secrets:** `.env` is gitignored and `.env.example` is kept current. No keys
  in git, ever.
- **Data hygiene:** no message content, tokens, or fields that look like PII in
  logs. Data minimization by default.
- **Boundary controls:** input validation with Pydantic, rate limiting through
  Redis, consistent problem details errors, and audit logging of sensitive actions.
- **Honesty controls:** README and SECURITY.md state plainly that this is a
  simulation. SECURITY.md documents what a real HIPAA deployment would
  additionally require (business associate agreements, encryption guarantees,
  access reviews, breach procedures, and more) without claiming any of it.
- Later phases deliver the threat model, the failure mode analysis, and the
  safety evaluation cases required by the spec.

---

## 9. Observability Architecture

Staged, free, and self hosted:

- **From Phase 1:** structured JSON logging (structlog) with correlation,
  request, workflow, and AI request IDs on every line, problem details errors,
  and health endpoints. This alone makes the slice debuggable.
- **Once the slice runs end to end:** Prometheus, Grafana, and OpenTelemetry
  (traces through the OTel SDK into Tempo or Jaeger, all free) inside the
  `observability` compose profile, which stays off by default to protect the laptop.
- **Metrics that matter:** application metrics (latency, throughput, errors,
  queue depth and consumer lag), AI metrics (tokens, cost both real and
  simulated, latency, structured output failure rate), workflow metrics
  (completion, retry, and failure rates, time to review), and product metrics
  (escalation rate, and the AI acceptance rate derived from clinician accept,
  edit, and reject events).
- **The ops console is the control plane,** distinct from Grafana dashboards:
  inspect active and failed workflows, the AI request log, the review queue,
  and the dead letter queues, retry workflows, and replay events idempotently.

---

## 10. Testing Strategy

| Tier | Scope | Tooling, all free |
|---|---|---|
| Unit | Domain logic, state machines, risk thresholds | pytest |
| Integration | Postgres repositories, Redis, Redpanda produce and consume, outbox relay | pytest with containers |
| API | Critical endpoints: authn, authz, validation, problem details | httpx with pytest |
| Workflow | Risk escalation success and failure paths: AI timeout, malformed output, dead letters, reviewer timeout | pytest |
| AI evaluation | Golden datasets (normal, ambiguous, safety sensitive, adversarial, injection, malformed output) run against the fake provider, so they are free, deterministic, and gated for regressions | the `evals/` runner |
| End to end | The vertical slice journey: student message, Dira reply, risk signal, clinician review, ops visibility | Playwright |
| Frontend | typecheck, lint, and component tests for AI labeling and state rendering | vitest and testing library |

Principles: behavioral coverage over test count, and every important failure
mode gets a test. `./scripts/verify.sh` is the single phase exit command:
backend tests plus lint, frontend typecheck plus lint plus tests, evals, and a
compose smoke check. Evaluation against real models is a documented optional
activity that will be flagged for budget before it ever runs.

---

## 11. Implementation Roadmap

**Vertical slice first,** per the priority in CLAUDE.md. The spec phases 1
through 8 are resequenced into slice phases S1 through S7. Each ends with a
runnable increment and a phase gate (`./scripts/verify.sh` plus documented exit
criteria). The school and guardian work (spec phase 9), the payer work (phase
10), and deep RAG (phase 6) come only after the slice works.

| Slice phase | Maps to spec | Delivers as a runnable increment |
|---|---|---|
| **S1, Foundation** | P1 | Compose stack (Postgres, Redis, Redpanda), backend skeleton in clean layers, Alembic migrations for identity, tenancy, and the conversation core, auth plus RBAC, a seed script, and `verify.sh`. Gate: stack up, tests green, authorized CRUD through the API. |
| **S2, Conversation API and student UI** | P2 subset | Conversation and message endpoints with resource level authorization, and a minimal Next.js student app with design system foundations and the AI labeling components. Gate: a student logs in, sends a message, and sees it persisted. |
| **S3, Events online** | P3 | Outbox and relay, `PatientMessageCreated` flowing to a worker through Redpanda, idempotent consumers, dead letters with retry. Gate: the event flow is demonstrable and the failure and replay paths are tested. |
| **S4, AI Gateway with the fake provider** | P4 | The gateway, prompt registry, structured outputs, `FakeLLMProvider` as the default, full AIRequest logging, and proof of the env var provider swap through a stub adapter test. Gate: gateway calls are logged, validated, and labeled simulated. |
| **S5, Dira minimal** | P5 subset | Dira replies in the student app on the fake provider, visible AI labeling, conversation memory, and the safety guardrail scaffolding. Gate: chat works end to end locally at zero cost. |
| **S6, Risk signal, escalation, and a minimal clinician workspace** | P7 plus a P8 subset | The Risk Signal agent with structured output, deterministic thresholds, the Risk Escalation workflow, and a review queue UI where a clinician accepts, edits, or rejects, all audited and evented. Gate: a safety scenario fixture drives message, signal, and human review end to end. |
| **S7, Ops console minimal, slice hardening** | P11 subset | Workflow, AI request, and dead letter inspection with retry and replay actions, the Playwright end to end journey, and the eval runner with a golden dataset regression gate. **Gate: the full vertical slice (student, Dira, risk signal, clinician, ops) runs end to end on one laptop, free.** |
| Then | P6, deeper P5 and P8, P9, P10, P11 to P17 | The RAG platform, richer Dira and workspace, school and guardian, payer, full ops, the observability stack, eval expansion, security hardening, performance, deployment docs, and the final review. |

Dependencies are strictly ordered: S3 needs S1. S4 is independent of S3 and can
overlap it, but S5 needs both. S6 needs S3, S4, and S5. S7 needs S6. The ADRs
(0001 Redpanda broker, 0002 fake provider default, 0003 outbox pattern, 0004
workflow engine in the repo) are written at the start of S1 and capture the
decisions approved here.

---

## 12. Risks and Tradeoffs

| Risk or tradeoff | Assessment | Mitigation |
|---|---|---|
| Redpanda uses the BSL license, not Apache | Fine for a free local portfolio project. No redistribution or managed service use | Kafka API compatibility means a compose file swap to Kafka if ever needed |
| The fake provider diverges from real LLM behavior | A real risk: prompts never tested on real models could be weak | Identical interface and schemas, failure mode injection, and an eval harness built to run the same golden sets against a real provider later, optional and budget flagged |
| Laptop resource limits | The full stack may strain the machine | Redpanda instead of Kafka, compose profiles, observability off by default, workers consolidated where harmless |
| The workflow engine grows too large | It could turn into a bad Temporal | The engine stays minimal: states, transitions, retries, history. Features are added only when a workflow needs them, gated by an ADR |
| Ten surfaces means scope explosion | The classic portfolio failure mode | The vertical slice gate S7 comes before any broadening, and phases end with runnable increments only |
| Simulated AI mistaken for real | This would violate the project honesty contract | The simulated flag flows from provider to log to API to a UI badge, enforced at every layer and tested |
| Continuity across many sessions | Context is lost between sessions | CLAUDE.md and docs/PROGRESS.md discipline, phase gates, conventional commits, ADRs |
| Cost creep through external services | You require zero cost | Everything is self hosted and open source. The only potential spend, real LLM APIs, is off by default and will be flagged before first use |

---

### External dependencies and cost statement

Every component proposed here (FastAPI, Next.js, PostgreSQL, Redis, Redpanda,
Prometheus, Grafana, OpenTelemetry, pytest, Playwright, uv, npm, Docker) is
free and runs locally. **No external paid service is required for any phase of
this roadmap.** The single future exception is optional use of real LLM APIs.
It is disabled by default, and you will be told explicitly before any phase
suggests enabling it.

### Requested approval

Approve this proposal, or request changes, to begin **Phase S1, Foundation**.
Per the build spec, nothing beyond documentation will be produced until then.
