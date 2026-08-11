# ADR 0001: Redpanda as the event broker

Status: accepted (approved with Phase 0, 2026-08-10)

## Context

The build spec requires a realistic event broker (Kafka or equivalent). The
project runs entirely on one laptop that may struggle with a full Kafka
deployment, and the budget is zero.

## Decision

Use Redpanda as the broker in local dev. It speaks the Kafka wire protocol, so
all client code uses standard Kafka libraries (aiokafka), standard topics,
partitions, consumer groups, and offsets.

## Alternatives considered

- Apache Kafka: the canonical choice, but the JVM stack needs far more memory
  and starts slowly on a laptop.
- Redis Streams: lighter still, but a different model that would undercut the
  spec requirement of a realistic broker.

## Consequences

- Local dev stays light (roughly 256 to 512 MB for the broker).
- Zero lock in: swapping to real Kafka is a compose file change because the
  protocol and client code are identical.
- Redpanda is source available under the BSL. That is fine for free local and
  self hosted use, which is all this project does.
