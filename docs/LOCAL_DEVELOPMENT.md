# LOCAL DEVELOPMENT

Everything runs locally and free. Prereqs: Docker, uv, Node 20 or 22
(CI uses 22; vitest 4 warns on 23).

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
./scripts/verify.sh          # the gate: lint, type check, migrations, tests with coverage, evals
./scripts/e2e.sh             # full browser journey (boots everything itself; once: cd frontend && npx playwright install chromium)
./scripts/gen-api-types.sh   # regenerate frontend types after API changes
docker compose --profile observability up -d   # Prometheus :9090, Grafana :3001
```

Backend only: `uv run pytest`, `uv run pytest -m integration`,
`uv run pytest --cov` (floor 80 percent, configured in pyproject),
`uv run ruff check . && uv run ruff format --check .`, `uv run mypy`,
`uv run python -m evals.run --dataset all`.

Frontend only: `npm run lint && npm run typecheck && npm run test`, and
`npm run build` for the production build CI also runs. `frontend/.npmrc`
pins `legacy-peer-deps` because npm 10.9's peer resolver crashes on
vitest 4's optional peer set; `vite` and `@testing-library/dom` are
explicit dev dependencies for that reason, and `npm ci` reproduces the
tree.

## Configuration

Copy `backend/.env.example` to `backend/.env`. Defaults work out of the
box. The interesting switches: `LLM_PROVIDER` (fake by default; real
providers are the only possible cost in the project), `EMBEDDING_PROVIDER`
(local lexical by default), rate limit knobs, `LOG_JSON`, database pool
sizes, `TRUST_PROXY_HEADERS` (only behind a proxy that sets
`X-Forwarded-For`), and `METRICS_TOKEN`.

## Test environment notes

Integration tests run against `caremesh_test` in the dockerized Postgres
(created by an init script on first container start) through the real
Alembic migrations, and against the real Redis and Redpanda. The suite
raises the login rate limit through an env var in `tests/conftest.py`
because fixtures sign in constantly. If the Postgres volume predates the
pgvector image switch, drop it and reseed.
