# OBSERVABILITY

What exists, how to run it, and what is deferred. This file describes
reality only.

## Structured logging (since S1)

Every process logs structured lines (structlog): JSON when `LOG_JSON=true`,
console format in dev. Every HTTP request carries a request id
(`X-Request-ID` in and out), bound to the log context and carried into
domain events as the correlation id, so one id follows a request from the
API through the outbox, the relay, and the consumer. Message content,
tokens, and PII like fields never appear in logs.

## Metrics (spec P12)

The API exposes Prometheus metrics at `GET /metrics`:

| Metric | Kind | Meaning |
|---|---|---|
| `caremesh_http_requests_total{method,path,status}` | counter | Requests; paths are normalized (`:id` for UUIDs) to bound cardinality |
| `caremesh_http_request_duration_seconds` | histogram | Latency by method and normalized path |
| `caremesh_ai_requests_total{provider,prompt,status,simulated}` | counter | Every AI Gateway call, including failures |
| `caremesh_ai_tokens_total{direction}` | counter | Input and output tokens |
| `caremesh_ai_cost_usd_total` | counter | Cumulative spend (0 on the fake provider) |
| `caremesh_workflows_by_state{workflow_type,state}` | gauge | Current workflow instances (refreshed every 15s from Postgres) |
| `caremesh_review_queue_depth` | gauge | Risk escalations waiting for a human |
| `caremesh_outbox_unpublished` | gauge | Events waiting for the relay; nonzero when the relay is down |

The workflow, review queue, and outbox gauges are refreshed by a
background task in the API (every 15 seconds), so they reflect database
truth, not in process guesses.

## Dashboards

The `observability` compose profile runs Prometheus and Grafana, off by
default to spare the laptop:

```bash
docker compose --profile observability up -d
# Prometheus: http://localhost:9090
# Grafana:    http://localhost:3001  (anonymous viewer; admin / caremesh-dev)
```

Grafana is provisioned from the repo (`docker/grafana/provisioning/`): the
Prometheus datasource and the "CareMesh overview" dashboard (request rate
by status, p95 latency, AI requests by prompt and outcome, tokens, spend,
review queue depth, outbox lag, workflows by state). Panel colors follow
the product palette rule: no blue.

## Deferred, on purpose

- **Worker metrics:** the relay and consumer processes do not expose
  `/metrics` yet; AI calls made in the consumer (risk analysis) are logged
  and audited in `ai_requests` but not counted in Prometheus. They get
  their own metrics ports when the workers are containerized.
- **Distributed tracing:** correlation ids across logs and events serve
  dev debugging today; OpenTelemetry tracing with a local backend is
  deferred until a phase needs span level visibility.
- **Alerting:** thresholds exist visually (queue depth, outbox lag);
  Prometheus alert rules come with the deployment phase.
