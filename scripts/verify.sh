#!/usr/bin/env bash
# Phase exit check. Runs every validation that exists so far and fails loudly.
# Sections for parts of the stack that do not exist yet are skipped with a note.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "==> docker compose services"
docker compose up -d --wait

echo "==> backend: lint"
(cd backend && uv run ruff check . && uv run ruff format --check .)

echo "==> backend: migrations apply cleanly to the dev database"
(cd backend && uv run alembic upgrade head)

echo "==> backend: tests (unit + integration)"
(cd backend && uv run pytest -q)

if [ -d frontend ]; then
  echo "==> frontend: lint, typecheck, tests"
  (cd frontend && npm run lint && npm run typecheck && npm run test)
else
  echo "==> frontend: not present yet, skipped"
fi

if [ -d backend/evals ]; then
  echo "==> evals: golden dataset"
  (cd backend && uv run python -m evals.run --dataset all)
else
  echo "==> evals: not present yet, skipped"
fi

echo "==> verify: all present checks passed"
