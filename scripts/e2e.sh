#!/usr/bin/env bash
# Runs the vertical slice E2E journey: boots the API, both workers, and the
# frontend, seeds demo data, drives a real browser, then cleans up.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

cleanup() {
  lsof -ti:8000 -sTCP:LISTEN 2>/dev/null | xargs kill 2>/dev/null || true
  lsof -ti:3000 -sTCP:LISTEN 2>/dev/null | xargs kill 2>/dev/null || true
  pkill -f "app.workers.relay" 2>/dev/null || true
  pkill -f "app.workers.conversation_consumer" 2>/dev/null || true
}
trap cleanup EXIT
cleanup

docker compose up -d --wait
(cd backend && uv run alembic upgrade head && uv run python -m scripts.seed >/dev/null)

(cd backend && uv run uvicorn app.main:app --port 8000 >/tmp/caremesh-e2e-api.log 2>&1 &)
(cd backend && uv run python -m app.workers.relay >/tmp/caremesh-e2e-relay.log 2>&1 &)
(cd backend && uv run python -m app.workers.conversation_consumer >/tmp/caremesh-e2e-consumer.log 2>&1 &)
(cd frontend && npm run dev >/tmp/caremesh-e2e-web.log 2>&1 &)

for _ in $(seq 1 60); do
  if curl -sf http://localhost:8000/healthz >/dev/null && curl -sf http://localhost:3000 >/dev/null; then
    break
  fi
  sleep 1
done

(cd frontend && node e2e/journey.mjs)
echo "e2e: passed"
