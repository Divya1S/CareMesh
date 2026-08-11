# ADR 0003: Outbox pattern for domain events

Status: accepted (approved with Phase 0, 2026-08-10)

## Context

Domain events must be reliable: a state change in Postgres and its event on the
broker must not drift apart. Writing to two systems in one request (a dual
write) can lose events or emit events for changes that rolled back.

## Decision

Domain events are written to an append only `DomainEventLog` table in the same
Postgres transaction as the state change. A relay process reads the outbox and
publishes to Redpanda, marking rows as published. Consumers are idempotent by
`event_id`, so at least once delivery is safe.

## Alternatives considered

- Publish directly to the broker inside the request: simplest, but a dual write
  with real inconsistency windows.
- Change data capture (Debezium): realistic at scale but heavy for a laptop and
  more moving parts than the project needs.

## Consequences

- Events can be replayed from the outbox, which the ops console will use.
- One more process (the relay) runs in compose.
- Delivery is at least once, so every consumer must be idempotent. That is a
  stated convention, and it is tested.
