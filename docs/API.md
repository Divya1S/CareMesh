# API

FastAPI serves OpenAPI at `/docs` and `/openapi.json`. Frontend TypeScript
types are generated from that schema (`scripts/gen-api-types.sh`), never
hand written.

## Conventions

- Versioned prefix `/api/v1`; health at `/healthz`; Prometheus at
  `/metrics`.
- Bearer JWT auth; 15 minute access tokens, rotating single use refresh
  tokens (`POST /api/v1/auth/refresh`).
- Errors are RFC 9457 problem details (`application/problem+json`) with
  stable codes; 401 carries `WWW-Authenticate`, 429 carries `Retry-After`.
  No bare 500s for expected failures.
- Every request gets an `X-Request-ID` (accepted inbound or generated),
  which becomes the correlation id on domain events and AI audit rows.
- Pagination by `limit`/`offset` with server side caps.
- Rate limits: login per client address and account; AI bearing endpoints
  (messages, knowledge ask) per user.

## Surfaces by role

| Prefix | Role | Purpose |
|---|---|---|
| `/api/v1/auth` | all | login, refresh, me |
| `/api/v1/conversations` | patient, assigned therapist | conversations, messages (Dira replies to patients) |
| `/api/v1/knowledge` | org members; ingest is ops only | resource library, grounded ask |
| `/api/v1/reviews` | therapist | risk review queue and decisions |
| `/api/v1/referrals`, `/api/v1/school/*` | therapist / school staff | referral workflow |
| `/api/v1/guardian/*` | guardian; share is therapist | portal overview, shared updates |
| `/api/v1/claims` | therapist, payer staff | eligibility, claims, decisions, history |
| `/api/v1/ops/*` | ops admin | workflows, AI requests, outbox, DLQ, republish |

Authorization is resource level inside use cases (assignment, links,
ownership), not just role gates; cross tenant reads return 404.
