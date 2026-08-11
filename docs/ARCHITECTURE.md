# ARCHITECTURE

## Shape

One backend service (FastAPI) plus two worker processes (relay, consumer)
sharing a codebase, one Next.js frontend, PostgreSQL with pgvector as the
source of truth, Redis for rate limiting, Redpanda as the event broker.
Everything runs locally through docker compose plus host processes; see
docs/LOCAL_DEVELOPMENT.md.

## Layer rules (enforced by convention and review)

```
backend/app/
  api/             thin route handlers: parse, auth context, call a use case
  application/     use cases, resource level authorization, the AI Gateway,
                   ports (Protocols) that infrastructure implements
  domain/          entities, state machines, events, ids. Zero framework
                   imports; plain dataclasses and pure functions
  infrastructure/  SQLAlchemy repositories, security, providers, metrics,
                   rate limiting, broker code
  workers/         relay (outbox to broker) and consumer (risk analysis)
```

- Route handlers never contain business logic.
- Authorization is decided in use cases at the resource level; the
  frontend hiding something is never the control.
- The domain layer is importable without any framework installed.
- Infrastructure depends inward; nothing imports from `api/`.

## Data flow guarantees

- **Writes and events are atomic:** domain events go to the
  `domain_event_log` outbox in the same transaction as the state change
  (ADR 0003). The relay publishes them; consumers are idempotent by event
  id, with the idempotency mark and all effects in one transaction.
- **Workflows are explicit:** every long running process is a state
  machine with validated transitions and append only history (ADR 0004).
- **AI is behind one door:** every model call goes through the gateway and
  is audited (see docs/AI_ARCHITECTURE.md).

## Key invariants

- Tenant isolation: every clinical row carries `organization_id` and every
  query scopes by it; cross tenant reads return 404.
- Provenance: message rows record sender type and, for AI messages, the
  `ai_request_id` and `simulated` flag; the UI renders provenance from
  data, not assumption.
- Events carry ids, never clinical text.
