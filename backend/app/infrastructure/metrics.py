"""Prometheus metrics (spec P12). Metrics that answer real questions:
is the API healthy, what is the AI doing and costing, is work piling up.

Path labels are normalized (UUIDs collapsed to :id) to keep cardinality
bounded. Worker processes do not expose metrics yet; that limitation is
documented in docs/OBSERVABILITY.md.
"""

import re

from prometheus_client import Counter, Gauge, Histogram

_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE)


def normalize_path(path: str) -> str:
    return _UUID.sub(":id", path)


HTTP_REQUESTS = Counter(
    "caremesh_http_requests_total",
    "HTTP requests handled",
    ["method", "path", "status"],
)

HTTP_DURATION = Histogram(
    "caremesh_http_request_duration_seconds",
    "HTTP request latency",
    ["method", "path"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)

AI_REQUESTS = Counter(
    "caremesh_ai_requests_total",
    "AI Gateway calls by outcome",
    ["provider", "prompt", "status", "simulated"],
)

AI_TOKENS = Counter(
    "caremesh_ai_tokens_total",
    "Tokens through the AI Gateway",
    ["direction"],
)

AI_COST = Counter(
    "caremesh_ai_cost_usd_total",
    "Cumulative AI spend in USD (0 on the fake provider)",
)

WORKFLOWS_BY_STATE = Gauge(
    "caremesh_workflows_by_state",
    "Current workflow instances by type and state",
    ["workflow_type", "state"],
)

OUTBOX_UNPUBLISHED = Gauge(
    "caremesh_outbox_unpublished",
    "Domain events waiting for the relay",
)

REVIEW_QUEUE_DEPTH = Gauge(
    "caremesh_review_queue_depth",
    "Risk escalations waiting for a human decision",
)
