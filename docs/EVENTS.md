# EVENTS

How domain events work in CareMesh, and the catalog of events that exist.
This file documents reality only; events land here when they ship.

## Mechanics

- **Broker:** Redpanda, spoken to with standard Kafka clients (aiokafka).
  ADR 0001.
- **Outbox (ADR 0003):** producers never write to the broker directly. A
  domain event is written to the `domain_event_log` table in the same
  Postgres transaction as the state change. The relay process
  (`app/workers/relay.py`, run with `uv run python -m app.workers.relay`)
  polls unpublished rows with FOR UPDATE SKIP LOCKED, publishes them, and
  stamps `published_at`. Rows are never deleted, so events can be replayed.
- **Envelope** (`app/infrastructure/events/schemas.py`): `event_id` (UUIDv7),
  `event_type`, `schema_version`, `occurred_at`, `organization_id`,
  `correlation_id` (the originating HTTP request id), `causation_id`,
  `payload`. Messages are keyed by `organization_id` so one tenant's events
  stay ordered per partition.
- **Topics:** `caremesh.<domain>.<event>`, snake case, for example
  `caremesh.conversation.patient_message_created`. Dead letters go to
  `<topic>.dlq`.
- **Delivery:** at least once. Every consumer records `(consumer_group,
  event_id)` in `processed_events` before acting, so duplicates are skipped
  (exactly once effect). Malformed payloads go straight to the DLQ;
  transient failures retry with backoff a bounded number of times first.
- **Data minimization:** payloads carry ids, never message content or other
  clinical text. Consumers that need content fetch it from Postgres.

## Catalog

### PatientMessageCreated, v1

- **Purpose:** a message was written into a conversation. Downstream phases
  hang risk analysis (S6) and projections off this fact.
- **Producer:** `ConversationService.post_message` (outbox, same
  transaction as the message insert).
- **Topic:** `caremesh.conversation.patient_message_created`
- **Consumers:** `caremesh-conversation-worker`
  (`app/workers/conversation_consumer.py`): validates, records idempotency,
  logs. Real risk logic plugs in here in S6.
- **Payload:** `message_id`, `conversation_id`, `patient_id`,
  `sender_type` (patient | clinician | dira | system). No content.
- **Failure behavior:** 3 attempts with exponential backoff for transient
  errors, then the raw record goes to
  `caremesh.conversation.patient_message_created.dlq`. Malformed records go
  to the DLQ immediately.
