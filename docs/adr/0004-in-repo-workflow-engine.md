# ADR 0004: Small workflow engine inside the repo

Status: accepted (approved with Phase 0, 2026-08-10)

## Context

The spec requires explicit orchestration for long running processes: visible
state transitions, retries, timeouts, compensation, human review steps, audit
history, and execution state inspectable from the ops console.

## Decision

Build a small workflow engine inside the repo on top of Postgres: a
`WorkflowInstance` table, declared state machines per workflow type, transition
functions, and event triggers. Transitions are recorded append only with actor,
reason, and correlation ID.

## Alternatives considered

- Temporal: excellent engine, but heavy for one laptop and it hides exactly the
  state machine engineering this portfolio project is meant to demonstrate.
- Celery chains or background tasks: opaque, no audit history, and business
  critical logic would live in anonymous tasks, which the spec forbids.

## Consequences

- We own retry and timeout logic, which is the point of the exercise.
- Scope risk: the engine stays minimal (states, transitions, retries, history)
  and gains features only when a concrete workflow needs them, gated by a new ADR.
