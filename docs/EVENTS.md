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

### AIResponseGenerated, v1

- **Purpose:** Dira produced a reply in a conversation. Feeds the AI
  observability and evaluation surfaces in later phases.
- **Producer:** `ConversationService._generate_dira_reply` (outbox, same
  transaction as the reply message; ADR 0005).
- **Topic:** `caremesh.ai.ai_response_generated`
- **Consumers:** none yet; the ops console and evaluation phases subscribe
  later.
- **Payload:** `message_id`, `conversation_id`, `ai_request_id`,
  `simulated`. No content.
- **Failure behavior:** standard outbox delivery; no consumer side effects
  yet.

### RiskSignalDetected, v1

- **Purpose:** the Risk Signal agent classified a patient message. Emitted
  for every analyzed message, escalated or not.
- **Producer:** `RiskAnalysisService` inside the conversation consumer, in
  the same transaction as the signal row and the idempotency mark.
- **Topic:** `caremesh.risk.risk_signal_detected`
- **Payload:** `risk_signal_id`, `message_id`, `conversation_id`,
  `patient_id`, `category`, `severity`, `escalated`. The evidence quote
  stays in the database, never in events.
- **Consumers:** none yet (ops and evaluation phases).

### RiskReviewRequired, v1

- **Purpose:** deterministic thresholds decided a human must review a
  signal; a Risk Escalation workflow was opened in `pending_review`.
- **Producer:** `RiskAnalysisService`, same transaction as the workflow row.
- **Topic:** `caremesh.risk.risk_review_required`
- **Payload:** `workflow_id`, `risk_signal_id`, `patient_id`, `severity`.
- **Consumers:** none yet (notification phases subscribe later; the review
  queue reads Postgres directly).

### HumanReviewCompleted, v1

- **Purpose:** a therapist accepted, edited, or rejected a signal. This is
  the clinician feedback stream that later feeds evaluation.
- **Producer:** `ReviewService.decide`, same transaction as the review row
  and the workflow transition to `resolved`.
- **Topic:** `caremesh.risk.human_review_completed`
- **Payload:** `workflow_id`, `risk_signal_id`, `reviewer_id`, `decision`,
  `severity_override`.
- **Consumers:** none yet (evaluation phase).

### ReferralSubmitted, v1

- **Purpose:** a school staff member referred a student to the care team; a
  referral workflow opened in `submitted`.
- **Producer:** `ReferralService.submit` (outbox, same transaction as the
  referral row and workflow).
- **Topic:** `caremesh.referral.referral_submitted`
- **Payload:** `referral_id`, `workflow_id`, `patient_id`, `submitted_by`.
  The concern text stays in the database.
- **Consumers:** none yet (notification phases).

### ReferralDecided, v1

- **Purpose:** a therapist accepted or declined a referral; the workflow is
  terminal. Acceptance also creates a care assignment.
- **Producer:** `ReferralService.decide`, same transaction as the workflow
  transition.
- **Topic:** `caremesh.referral.referral_decided`
- **Payload:** `referral_id`, `workflow_id`, `patient_id`, `decided_by`,
  `decision` (accepted | declined).
- **Consumers:** none yet.

### GuardianNotificationRequired, v1

- **Purpose:** something happened that a linked guardian should hear about
  (referral accepted, care update shared). The notification row is the
  source of truth; this event feeds delivery channels later.
- **Producer:** `ReferralService._notify_guardians` and
  `GuardianService.share_update`, same transaction as the notification row.
- **Topic:** `caremesh.guardian.guardian_notification_required`
- **Payload:** `notification_id`, `guardian_id`, `patient_id`, `kind`
  (referral_accepted | care_update). Content stays in the database.
- **Consumers:** none yet (email or push delivery would subscribe here).

### InsuranceClaimSubmitted, v1

- **Purpose:** a therapist submitted a claim; a claim workflow opened in
  `submitted`. Submission requires a passing eligibility check from the
  labeled payer adapter.
- **Producer:** `ClaimsService.submit` (outbox, same transaction as the
  claim row and workflow).
- **Topic:** `caremesh.billing.insurance_claim_submitted`
- **Payload:** `claim_id`, `workflow_id`, `patient_id`, `submitted_by`,
  `amount_cents`.
- **Consumers:** none yet.

### InsuranceClaimUpdated, v1

- **Purpose:** a claim changed state: approved or denied by payer staff, or
  resubmitted by the therapist. Denial reasons and resubmission notes live
  on the claim row; the workflow transition history carries them too.
- **Producer:** `ClaimsService.decide` and `ClaimsService.resubmit`, same
  transaction as the workflow transition.
- **Topic:** `caremesh.billing.insurance_claim_updated`
- **Payload:** `claim_id`, `workflow_id`, `state`, `actor_id`.
- **Consumers:** none yet.
