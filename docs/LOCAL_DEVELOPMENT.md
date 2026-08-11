# LOCAL DEVELOPMENT

Everything runs locally and free. Prereqs: Docker, uv, Node 20+.

## First run

```bash
docker compose up -d                       # postgres :5433, redis :6379, redpanda :9092
cd backend
uv sync
uv run alembic upgrade head
uv run python -m scripts.seed              # demo org, six role accounts, resource docs
uv run uvicorn app.main:app --port 8000
```

In separate terminals:

```bash
cd backend && uv run python -m app.workers.relay
cd backend && uv run python -m app.workers.conversation_consumer
cd frontend && npm install && npm run dev   # http://localhost:3000
```

Demo password for every account: `caremesh-demo` (accounts listed in the
README). Postgres publishes on host port 5433 because many machines run a
local Postgres on 5432; connection strings in `.env.example` already point
there.

## Daily commands

```bash
./scripts/verify.sh          # the gate: lint, migrations, all tests, all evals
./scripts/e2e.sh             # full browser journey (boots everything itself)
./scripts/gen-api-types.sh   # regenerate frontend types after API changes
docker compose --profile observability up -d   # Prometheus :9090, Grafana :3001
```

Backend only: `uv run pytest`, `uv run pytest -m integration`,
`uv run ruff check . && uv run ruff format --check .`,
`uv run python -m evals.run --dataset all`.

Frontend only: `npm run lint && npm run typecheck && npm run test`.

## Configuration

Copy `backend/.env.example` to `backend/.env`. Defaults work out of the
box. The interesting switches: `LLM_PROVIDER` (fake by default; real
providers are the only possible cost in the project), `EMBEDDING_PROVIDER`
(local lexical by default), rate limit knobs, `LOG_JSON`.

## Test environment notes

Integration tests run against `caremesh_test` in the dockerized Postgres
(created by an init script on first container start) through the real
Alembic migrations, and against the real Redis and Redpanda. The suite
raises the login rate limit through an env var in `tests/conftest.py`
because fixtures sign in constantly. If the Postgres volume predates the
pgvector image switch, drop it and reseed.
