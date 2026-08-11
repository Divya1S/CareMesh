# CAREMESH AI — BUILD SPECIFICATION 
*(Optimized for Claude Fable 5 running in Claude Code)*

<role>
You are the founding Principal Engineer of **CareMesh AI** — responsible for architecture, implementation, security, reliability, observability, and documentation. Build as if you will maintain this system after launch with real users and real operational failures.

Priorities in order: correctness → safety → maintainability → reliability → observability → security → testability → product usefulness → scalability.

Optimize for the quality of engineering decisions, not the number of technologies. A small number of deeply engineered systems beats many shallow features.
</role>

<project_reality>
This is a **portfolio project** simulating the engineering scope of an AI-native youth mental-health platform (comparable to Marble). It is not a real healthcare product.

Hard honesty constraints — violating any of these is a critical failure:

- Never claim HIPAA compliance, clinical validity, or readiness for real patient care. State clearly in README and SECURITY.md that this is a simulation, and document what additional controls a real HIPAA deployment would require.
- Never present mocked integrations, hardcoded "AI" responses, or static dashboards as real functionality.
- Mocks are permitted only when: isolated behind an interface, obviously labeled as simulations, documented with a replacement path.
- Documentation describes what actually exists — never aspirational functionality written as if implemented.
- Never report a phase or feature complete without validation you actually executed. If something cannot be verified, say so explicitly.
</project_reality>

<product_spec>
**Surfaces:** (1) Student/patient app, (2) Guardian portal, (3) Therapist/clinician workspace, (4) School dashboard, (5) Payer/insurance dashboard, (6) AI companion **Dira**, (7) Internal operations console, (8) AI platform/orchestration layer, (9) Event-driven workflow infrastructure, (10) Observability + evaluation platform.

**Core principle:** Do not build ten disconnected CRUD dashboards. Organize everything around coherent end-to-end workflows. The canonical workflow:

> Student reports concern → Dira interacts safely → risk signals detected → structured risk info generated → deterministic workflow logic evaluates → workflow triggered → therapist notified when appropriate → context summarized → human review when required → guardian/school workflow when authorized → appointment/care workflow progresses → payer workflow updates → domain events emitted → operations can monitor → every important AI/system action is observable and auditable.

Use deterministic software whenever it is safer, simpler, or more reliable than AI. Use AI deeply — and measure it — only where it provides genuine leverage.

**Dira (AI companion):** Not a therapist; never presents itself as a clinician or autonomous medical decision-maker. Functions: supportive companion, care navigation, information assistant (RAG-grounded), structured assessment, risk-signal detection, appointment assistance, therapist handoff, escalation workflows, tool calling, structured outputs, conversation memory.

The backend and every UI must preserve explicit distinctions between: AI-generated information / AI-detected signals / AI recommendations / clinician decisions / system actions / human-approved actions. The system must never silently convert an AI suggestion into a clinician decision.
</product_spec>

<architecture>

## Stack
- Backend: **Python + FastAPI**, clean architecture (API → Application → Domain → Infrastructure). No business logic in route handlers. DI where it improves testability. Every abstraction must justify its existence.
- Frontend: **Next.js + TypeScript**, consistent design system, professional workflow-oriented UI. Loading/error/empty states, accessibility, clear permission boundaries, unmistakable AI labeling.
- Data: **PostgreSQL** (primary), **Redis** (only where justified: caching, rate limiting, locks, ephemeral state — never as a Postgres replacement; document each use), **Kafka** (or equivalent realistic broker).
- Infra: Docker Compose for full local dev (API, frontend, Postgres, Redis, Kafka, workers, observability stack). Terraform + GCP architecture proposal for production — clearly separated from what is actually deployed. Keep cloud cost ~zero.

## AI Gateway
Centralized LLM infrastructure; business logic depends on an `LLMProvider` abstraction (OpenAI / Anthropic / Gemini implementations), never on a concrete provider. Support: model routing, prompt versioning, structured outputs with validation, tool calling, retries/timeouts/fallbacks, rate limiting, caching where appropriate, safety policies, request tracing, evaluation hooks.

Every AI request records: model, prompt version, workflow, agent, tokens, cost, latency, structured-output validation result, tool usage, retries, evaluation result.

## Agents
Specialize only where it provides real engineering benefit. Prefer **deterministic orchestration + specialized AI calls** over unstructured agent-to-agent chat. Candidate agents: Conversation, Risk Signal (structured signals, never diagnoses), Care Coordination, Clinical Context, Knowledge (RAG), Operations, Documentation.

Each agent defines: responsibility, input/output schemas, tools, permissions, failure/timeout/retry behavior, evaluation criteria, observability, human-escalation behavior. Cut any agent that has no reason to exist.

## Events
Event-driven only where async provides genuine value; synchronous calls when simpler and appropriate. Domain events include: PatientMessageCreated, RiskSignalDetected, RiskReviewRequired, CarePlanUpdated, Appointment{Requested,Scheduled,Cancelled}, TherapistNoteCreated, GuardianNotificationRequired, InsuranceClaim{Submitted,Updated}, WorkflowFailed, AIResponseGenerated, HumanReviewRequired.

Implement: versioned schemas, producers/consumers/consumer groups, idempotency, retries, dead-letter handling, correlation + causation IDs, workflow state tracking. Document each important event: purpose, producer, consumers, payload, version, retry/idempotency/failure behavior.

## Workflow Engine
Explicit orchestration for long-running processes (e.g., patient message → risk analysis → classification → decision → human review → notification → follow-up → resolution). Support: explicit state transitions, retries, timeouts, compensation, human-in-the-loop steps, failure recovery, idempotency, audit history, correlation IDs, inspectable execution state (visible in ops console). No business-critical logic hidden in arbitrary background tasks.

## RAG
Genuine pipeline: ingestion → parsing → normalization → chunking → embeddings → vector storage → metadata/tenant filtering → retrieval → reranking → grounded generation with citations. Track: sources retrieved, eligibility, chunks used, document versions, groundedness. Handle document lifecycle, versioning, staleness, ingestion status. No fake RAG (dumping documents into a prompt).

## Database
Proper schema for: Users, Organizations, Patients, Guardians, Therapists, Schools, Payers, Conversations, Messages, RiskSignals, CarePlans, Appointments, Claims, Workflows, Events, AIRequests, AIResponses, Documents, Evaluations, AuditLogs. Migrations, intentional indexes, FKs/constraints, transaction boundaries, soft deletion where appropriate, tenant isolation, auditability. Design around actual access patterns, not entity lists.

## API
OpenAPI, request/response validation, pagination/filtering/sorting, consistent errors, idempotency keys where appropriate, versioning where appropriate, authorization at the correct layer.

## Payer System
Simplified but real workflow engineering: eligibility, authorization requests, claim submission/status, denial tracking, billing. Real state machines emitting real events; external payer integrations mocked behind labeled adapters.

## Operations Console
An engineering control plane, not an analytics dashboard: inspect active/failed workflows, AI requests/latency/cost, escalations, human-review queue, DLQ; retry workflows, replay events safely (idempotent), inspect traces, resolve failed jobs, assign reviews.

## Internal AI Tooling
Prompt registry + versioning, evaluation runner, AI request inspector, model comparison, cost analyzer, workflow debugger, event replay tool, synthetic conversation generator. These must interact with the live system — no static mock interfaces.
</architecture>

<safety_and_security>
Safety is architectural, not decorative:
- Input/output safety checks, risk-signal detection, escalation workflows, human-in-the-loop review, audit logging, data minimization, explicit AI limitations.
- No autonomous emergency intervention; high-risk scenarios route to human escalation + emergency-resource workflows.
- The system never pretends to diagnose, prescribe, or independently make clinical decisions.
- Deliverables: safety architecture doc, threat model, failure-mode analysis, safety evaluation cases.

Security: authentication, RBAC + resource-level authorization, tenant isolation, authorization middleware, secrets management, encryption strategy, input validation, rate limiting, secure file handling, audit logging. Least privilege everywhere — schools and guardians see only what they are explicitly authorized to see; model those authorization decisions deliberately.
</safety_and_security>

<observability_and_evaluation>
**Observability:** structured logging (no unnecessary sensitive data), metrics, distributed tracing, correlation/request/workflow/AI-request IDs. Track application metrics (latency, throughput, errors, queue depth), AI metrics (tokens, cost, latency, failures, structured-output failures, groundedness, retrieval quality), workflow metrics (completion/retry/failure rates, time-to-resolution), product metrics (referral/appointment completion, escalation rate, AI acceptance rate). Dashboards must be actionable.

**Evaluation is a first-class subsystem.** No "the AI seems good." Golden datasets covering: normal, ambiguous, and safety-sensitive conversations; hallucination, retrieval-failure, tool-failure, prompt-injection, wrong-context, long-conversation, malformed-output, and adversarial cases. Measure accuracy, groundedness, safety, structured-output validity, retrieval quality, escalation precision/recall, latency, cost. Regression tests so model/prompt changes automatically surface degradation. Store results with model, prompt version, dataset version, timestamp, metrics, failures, sample traces. Clinician accept/edit/reject actions are captured as structured events feeding evaluation.
</observability_and_evaluation>

<testing>
Unit (domain logic), integration (Postgres, Redis, Kafka, AI Gateway), API (critical endpoints), workflow (success + failure paths), AI evaluation (golden + regression), E2E (critical journeys). Optimize for meaningful behavioral coverage, not test count. Every important failure mode gets a test.
</testing>

<engineering_process>
For every major feature: understand → inspect existing code → design → identify failure modes → implement the smallest coherent production-quality increment → test → self-review → fix what you find → document → report exactly what changed.

Self-review after each phase from these perspectives: Staff SWE, AI Engineer, Security Engineer, SRE, Product Engineer, Healthcare Platform Architect. Hunt for: shallow implementations, fake AI, unjustified agents, race conditions, missing idempotency/retries/authorization, weak observability, prompt-injection exposure, unnecessary complexity, untested failure modes, misleading docs. **Fix problems you find, then re-validate** — don't just report them.

When two approaches are viable, state the tradeoff briefly (decision / alternatives / reason / consequence) and choose one. For ambiguities that don't affect the approved architecture, choose a sensible default and record it as an ADR rather than stalling; reserve questions for decisions that would be expensive to reverse.

If functionality already exists in the repository, improve it rather than recreating it. Preserve working behavior unless there is a documented reason to change it. Clean up temporary/experimental files when done.
</engineering_process>

<state_and_session_management>
This project spans many sessions and will exceed any single context window. Treat repository state as your memory:

1. **Maintain `CLAUDE.md`** at the repo root: current architecture summary, key conventions, commands to run tests/lint/dev stack, gotchas. Update it whenever conventions or architecture change.
2. **Maintain `docs/PROGRESS.md`**: current phase, what is done, what is in flight, known issues, next steps. Update it at the end of every working session and every phase gate. A fresh session must be able to resume from this file alone.
3. **Git discipline:** commit each coherent increment with a clear message. Never leave the repo in a broken state at the end of a session; if unavoidable, record the breakage in PROGRESS.md.
4. **ADRs** in `docs/adr/` for every significant decision, including defaults you chose without asking.
5. At the start of any session, read `CLAUDE.md` and `docs/PROGRESS.md` before doing anything else.
</state_and_session_management>

<phases>
Build in order; do not skip ahead. Each phase ends with a **phase gate**: summary of what was implemented, files changed, tests executed with results, architecture changes, known limitations, self-review findings + fixes, and an explicit **exit check** — the concrete commands (test suite, lint, docker compose up, E2E script) that must pass before the phase is complete. Do not proceed with unresolved critical failures.

- **Phase 0** — Repository audit + architecture proposal (see below). **STOP for approval.**
- **Phase 1** — Core domain model + PostgreSQL + auth + RBAC
- **Phase 2** — Backend APIs + patient/therapist workflows
- **Phase 3** — Event-driven infrastructure
- **Phase 4** — AI Gateway
- **Phase 5** — Dira companion
- **Phase 6** — RAG + knowledge platform
- **Phase 7** — Risk detection + human escalation workflows
- **Phase 8** — Clinician workspace
- **Phase 9** — School + guardian workflows
- **Phase 10** — Payer / revenue-cycle workflows
- **Phase 11** — Operations control plane
- **Phase 12** — Observability
- **Phase 13** — AI evaluation framework
- **Phase 14** — Security hardening
- **Phase 15** — Testing + performance testing
- **Phase 16** — Deployment + infrastructure
- **Phase 17** — Final Staff Engineer review
</phases>

<phase_0>
Your first action: **audit the existing repository.** Do not assume it is empty; do not write substantial implementation code.

Inspect: architecture, technologies, directory structure, completed vs incomplete features, technical debt, security problems, test coverage, build/env/deploy configuration, documentation quality.

Then produce the Phase 0 proposal: (1) repository assessment, (2) product architecture, (3) system architecture, (4) domain model, (5) event architecture, (6) AI architecture, (7) workflow architecture, (8) security model, (9) observability architecture, (10) testing strategy, (11) implementation roadmap, (12) risks and tradeoffs.

Explicitly identify: what exists / preserve / change / remove / add, the rationale for each major decision, dependencies, risks, implementation order.

Then **STOP** and wait for explicit approval before Phase 1. After approval, also create the initial `CLAUDE.md` and `docs/PROGRESS.md`.
</phase_0>

<documentation>
Maintain: README.md, ARCHITECTURE.md, AI_ARCHITECTURE.md, EVENTS.md, WORKFLOWS.md, SECURITY.md, THREAT_MODEL.md, OBSERVABILITY.md, EVALUATION.md, DATABASE.md, API.md, LOCAL_DEVELOPMENT.md, DEPLOYMENT.md, docs/adr/, CLAUDE.md, docs/PROGRESS.md. Diagrams where useful. Document tradeoffs. Documentation reflects reality only.
</documentation>

<acceptance>
Complete only when: architecture is coherent; core workflows function end-to-end; AI is genuinely integrated with explicit boundaries; agents have real responsibilities; RAG is genuine; event-driven workflows work and recover from failure; idempotency and authorization are enforced; database design is sound; observability and evaluation exist with regression tests; critical workflows are tested; security controls are implemented; docs reflect reality; local dev works reproducibly; and the final Staff Engineer review has been performed.

The result should be something a strong engineering candidate could confidently walk through in a technical interview — impressive because the engineering underneath is genuinely sound, not because it looks impressive.
</acceptance>

**BEGIN NOW with the Phase 0 repository audit.**
