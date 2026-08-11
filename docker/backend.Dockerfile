# CareMesh backend image: API and workers from one build, selected by the
# compose command. Build context is the repo root:
#   docker compose --profile app build
#
# Two stages so the final image carries the virtualenv but not uv's caches.

FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS builder
WORKDIR /srv/backend
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
# Dependency layer first so code edits do not reinstall the world.
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev
COPY backend/ ./
RUN uv sync --frozen --no-dev

FROM python:3.13-slim-bookworm
WORKDIR /srv/backend
ENV PATH="/srv/backend/.venv/bin:$PATH" PYTHONUNBUFFERED=1
COPY --from=builder /srv/backend /srv/backend
# Non root: nothing here needs privileges.
RUN useradd --system --no-create-home caremesh
USER caremesh
EXPOSE 8000
# Default command runs the API; compose overrides it for the workers.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
