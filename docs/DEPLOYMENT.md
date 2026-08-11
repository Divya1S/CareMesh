# DEPLOYMENT

> **This document is a paper design. CareMesh has never been deployed
> anywhere.** Everything runs locally at zero cost (see the Quickstart in
> the README). This page records how the system would map onto managed
> infrastructure, because the mapping is part of the architecture, not
> because it happened.

## What exists today

- One backend image (`docker/backend.Dockerfile`) runs the API, the
  outbox relay, and the event consumer, selected by command. The compose
  `app` profile runs all three as containers against the dockerized
  Postgres, Redis, and Redpanda, and the full chat to risk signal
  pipeline was verified against that containerized stack.
- Configuration is entirely env vars with safe dev defaults, and the
  settings module fails closed outside dev if the JWT secret is still
  the dev value.
- Migrations are a one shot container (`migrate`) the others wait on,
  which is the same shape a deploy job would take.

## Paper target: GCP

Chosen for the proposal because Cloud Run's scale to zero keeps a demo
deployment near free. The equivalent AWS mapping (App Runner or ECS,
RDS, ElastiCache, MSK) would work the same way.

| Local piece | Managed equivalent | Notes |
|---|---|---|
| API container | Cloud Run service | Stateless, scale to zero, one concurrency tuned instance is enough for a demo |
| Relay and consumer | Cloud Run jobs or a minimal GKE Autopilot deployment | They poll and consume; they need to run always on, so this is the main cost line |
| Postgres + pgvector | Cloud SQL for PostgreSQL | pgvector is supported; automated backups replace the disposable dev volume |
| Redis | Memorystore | Same three uses only: rate limits, caching, locks |
| Redpanda | Confluent Cloud basic tier or self hosted Redpanda on a small VM | The code speaks the Kafka protocol either way; topic names and consumer groups carry over unchanged |
| .env | Secret Manager | JWT secret, database URL, LLM_API_KEY |
| /metrics + Grafana | Managed Prometheus + Grafana Cloud free tier | The dashboard JSON is provisioned code and would move as is |
| GitHub Actions CI | Same, plus an image push to Artifact Registry and a deploy step | The verify gate already runs the full suite on every push |

## What would have to change before any real deployment

Recorded honestly, since none of it is done:

1. Refresh tokens move from localStorage to httpOnly cookies.
2. TLS everywhere and a real CORS origin list.
3. Broker authentication (local Redpanda runs open).
4. A WAF or global rate limiter in front of the API.
5. Real secrets rotation and per environment JWT secrets.
6. And the honesty rule above all of it: this is a portfolio simulation;
   nothing here is validated for real patients or real clinical data.
