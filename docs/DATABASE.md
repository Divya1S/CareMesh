# DATABASE

PostgreSQL 16 with pgvector (image `pgvector/pgvector:pg16`), migrated by
Alembic (`backend/migrations/`). UUIDv7 primary keys everywhere (time
ordered, index friendly, generated in `app/domain/ids.py`).

## Table groups

- **Identity and tenancy:** `organizations`, `users` (role enum, Argon2
  hash), `auth_sessions` (refresh token rotation), `care_assignments`
  (therapist to patient), `guardian_links` (explicit guardian
  authorization).
- **Conversation core:** `conversations`, `messages` (sender type enum;
  AI provenance columns `ai_request_id`, `simulated`).
- **Risk and review:** `risk_signals` (append only, full AI provenance),
  `risk_reviews` (one human decision per signal).
- **Workflows:** `workflow_instances`, `workflow_transitions` (append
  only history).
- **Events:** `domain_event_log` (transactional outbox; partial index on
  unpublished), `processed_events` (consumer idempotency ledger, primary
  key on group plus event id).
- **AI:** `ai_requests` (every gateway call including failures),
  `rag_retrievals` (what each question retrieved and cited).
- **Knowledge:** `documents` (versioned by source name with a status
  lifecycle), `document_chunks` (`vector(384)` with an HNSW cosine index).
- **Billing:** `eligibility_checks` (adapter and simulated flag stored),
  `claims` (denial reason, resubmission note).
- **Audit:** `audit_logs` (append only, written in its own transaction).

## Access pattern driven indexes

Conversation timeline (`conversation_id, created_at`), clinician queue
(workflow state plus signal severity), org scoped listings
(`organization_id, created_at` on signals, claims, referrals), unpublished
outbox (partial index), chunk similarity (HNSW).

## Rules

- Append only tables are never updated or deleted: signals, transitions,
  events, AI requests, audit rows.
- Soft deletion is not used yet; nothing needed it. Add per table when a
  surface requires it, not speculatively.
- Two operational gotchas (parent flush ordering without ORM
  relationships; init scripts only run on first container start) are
  recorded in CLAUDE.md and in code comments where they bit.
