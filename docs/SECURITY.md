# SECURITY

> **This is a portfolio simulation.** CareMesh is not a real healthcare
> product, is not HIPAA compliant, holds no real patient data, and must
> never be used for real care. This document describes the controls that
> actually exist in the code, then lists what a real deployment would
> additionally require.

## Controls that exist (all tested)

**Authentication.** Email plus Argon2id password hashing. Short lived JWT
access tokens (15 minutes) and rotating refresh tokens: each refresh token
is single use, backed by a database session row, and a replayed token is
rejected. Login verifies a dummy hash for unknown emails so response
timing does not reveal account existence.

**Authorization.** RBAC (patient, guardian, therapist, school_staff,
payer_staff, ops_admin) plus resource level checks in the application
layer: therapists reach only assigned patients, guardians only explicitly
linked and shared items, schools only a names only roster and their own
referral states, payer staff only claims. Cross tenant access reads as
404 so tenants cannot probe each other. The frontend hides nothing that
the API does not also refuse.

**Rate limiting** (Redis, its one documented use): login attempts are
limited per client address and target account (default 5 per minute), and
AI bearing endpoints (chat messages, knowledge questions) are limited per
user (default 20 per minute). Exceeding a limit returns a problem details
429 with Retry-After.

**Audit trail.** Append only `audit_logs` rows for sensitive actions:
login success and failure (failures store a masked email, never the full
address), risk review decisions, claim decisions, and ops event
republishes. Audit writes use their own transaction so they survive the
request rollback they are documenting. Domain events and workflow
transition history provide the audit trail for everything else.

**Data hygiene.** No message content, tokens, or PII like fields in logs
or event payloads; events carry ids only. AI request logging stores
prompts and responses in the database for the ops inspector, never in
logs. DLQ previews are hard truncated.

**Boundary controls.** Pydantic validation on every request body, length
bounds on free text, consistent problem details errors (no bare 500s for
expected failures), CORS restricted to the dev frontend origin.

**Secrets.** `.env` is gitignored, `.env.example` stays current, the dev
JWT secret fails closed outside the dev environment, and no keys exist in
the repository or its history.

**AI safety controls.** All model access goes through the gateway (audit,
timeout, validation); the risk pipeline's escalation decision is
deterministic code, not model output; every AI element is labeled,
simulated output doubly so; safety properties of Dira's replies are
regression tested in the eval suites.

## Known limitations (deliberate, documented)

- Frontend tokens live in localStorage. Acceptable for a local portfolio
  demo; the documented fix is httpOnly cookies behind Next.js route
  handlers, which also removes the need for the client side refresh dance.
- Password policy is length bounds only; no complexity rules, breach
  checks, or MFA.
- Rate limiting covers login and AI endpoints, not every route.
- The API and workers run without TLS locally.

## What a real deployment would additionally require

Business associate agreements and a HIPAA compliance program; encryption
at rest with managed keys and TLS everywhere; MFA and SSO for staff;
session and device management; formal access reviews and break glass
procedures; data retention, deletion, and export workflows; consent
management as a legal record rather than a checkbox; intrusion detection,
alerting, and an incident response plan; penetration testing; and a
privacy review of every AI data flow. None of that exists here, and this
repository does not claim otherwise.
