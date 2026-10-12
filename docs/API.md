# API

FastAPI serves OpenAPI at `/docs` and `/openapi.json`. Frontend TypeScript
types are generated from that schema (`scripts/gen-api-types.sh`), never
hand written.

## Conventions

- Versioned prefix `/api/v1`; health at `/healthz`; Prometheus at
  `/metrics`.
- Bearer JWT auth with issuer and audience claims; 15 minute access
  tokens, rotating single use refresh tokens in families
  (`POST /api/v1/auth/refresh`): presenting an already rotated token
  revokes every token in its family.
- Errors are RFC 9457 problem details (`application/problem+json`) with
  stable codes; 401 carries `WWW-Authenticate`, 429 and 503 carry
  `Retry-After`. A decision on a workflow that is no longer in the
  expected state (someone else decided first, or the state machine
  refuses the move) is a 409. Model failures are upstream failures: 502
  (provider or validation) and 504 (timeout). No bare 500s for expected
  failures.
- Every `/api` response carries `X-Content-Type-Options: nosniff`,
  `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, and
  `Cache-Control: no-store`.
- Every request gets an `X-Request-ID` (accepted inbound or generated),
  which becomes the correlation id on domain events and AI audit rows.
- Pagination by `limit`/`offset` with server side caps; the messages list
  accepts `order=desc` for the newest page, which the chat loads.
- Rate limits: login and refresh per client address, login per account;
  AI bearing endpoints (messages, knowledge ask) per user. When the
  limiter store is unreachable, login fails closed (503) and AI endpoints
  fail open. Behind a reverse proxy, `TRUST_PROXY_HEADERS=true` buckets on
  the first `X-Forwarded-For` address.
- `/healthz` returns the database state (503 when down) and the Redis
  state (`degraded`, not failing). `/metrics` is open by default and
  requires `Authorization: Bearer <METRICS_TOKEN>` when that setting is
  present.

## Surfaces by role

| Prefix | Role | Purpose |
|---|---|---|
| `/api/v1/auth` | all | login, refresh, me |
| `/api/v1/conversations` | patient, assigned therapist | conversations, messages (Dira replies to patients) |
| `/api/v1/knowledge` | org members; ingest is ops only | resource library, grounded ask |
| `/api/v1/reviews` | therapist | risk review queue (newest 100 pending, by severity then age) and decisions |
| `/api/v1/referrals`, `/api/v1/school/*` | therapist / school staff | referral workflow |
| `/api/v1/guardian/*` | guardian; share is therapist | portal overview, shared updates |
| `/api/v1/claims` | therapist, payer staff | eligibility, claims, decisions, history |
| `/api/v1/ops/*` | ops admin | workflows, AI requests, outbox, DLQ, republish |

Authorization is resource level inside use cases (assignment, links,
ownership), not just role gates; cross tenant reads return 404.
