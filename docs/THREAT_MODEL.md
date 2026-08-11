# THREAT MODEL

A working threat model for the simulation, kept honest: threats are listed
with the mitigation that exists in code, or with an explicit gap.

## Assets

Clinical conversation content and risk signals (most sensitive), guardian
shared updates, referral concerns, claims and billing data, credentials
and sessions, the audit and event trails themselves.

## Actors and trust boundaries

Six user roles with distinct surfaces; the API boundary (browser to
FastAPI); the broker boundary (API and workers to Redpanda); the AI
boundary (application to LLM provider through the gateway); the database.
Every role to role boundary is enforced server side in the application
layer.

## Threats and mitigations

| Threat | Mitigation in code | Gap |
|---|---|---|
| Credential stuffing / brute force | Argon2id, per address and account login rate limit, timing equalized lookups, audit of failures with masked emails | No MFA, no breach password checks |
| Stolen refresh token replay | Single use rotating refresh tokens backed by DB sessions; replay is rejected and the session revoked | Tokens in localStorage until the cookie refactor |
| Horizontal privilege escalation (patient reads another patient) | Resource level checks in every use case; tested per surface | — |
| Cross tenant data access | organization_id scoping in every query; cross tenant reads return 404; tested | Single database, no row level security as defense in depth |
| School or guardian overreach | Structural least privilege: roster is names only, guardians see only linked and explicitly shared items; both tested | — |
| Prompt injection via patient messages | The AI never makes decisions: escalation is deterministic code over structured output; schema validation rejects malformed output; injection cases are regression tested in evals | A real LLM could still be steered in wording; content filters would be needed |
| AI cost or resource abuse | Per user rate limit on AI endpoints; every call audited with tokens and cost; fake provider costs nothing | — |
| Malicious or malformed events on the broker | Consumers validate envelopes, are idempotent by event id, and dead letter poison messages after bounded retries | Broker has no authentication in local dev |
| Tampering with audit or event history | Both tables are append only by convention and code path | No cryptographic chaining; DB admin could rewrite |
| Sensitive data in logs or metrics | No content in logs, id only event payloads, normalized metric labels, truncated DLQ previews; tested for metrics labels | — |
| Denial of service | Rate limits on the expensive paths, bounded page sizes, timeouts on AI calls | No global request limiter or WAF |

## Failure modes (safety analysis)

| Failure | Behavior built and tested |
|---|---|
| AI provider down or slow | Gateway timeout; Dira reply skipped without blocking the patient's message; risk analysis retries then dead letters; everything audited |
| AI returns malformed output | Bounded validation retry, then typed failure; the message is never silently dropped and never silently accepted |
| Relay or consumer crash | Outbox holds events (visible as a gauge and in ops); replay is safe because consumers are idempotent; one transaction covers idempotency mark and effects |
| Reviewer never acts | Queue depth is a metric with dashboard thresholds; escalation timeout automation is future work |
| False negative risk signal | The deterministic threshold escalates self harm and crisis categories regardless of severity score; clinicians see full conversations, not only flagged ones |
| False positive flood | Human review gate before any care consequence; clinician reject decisions are captured as events for eval feedback |

## Review cadence

Revisit this document whenever a new surface, event consumer, or external
integration lands. Last reviewed: 2026-08-10, security hardening phase.
