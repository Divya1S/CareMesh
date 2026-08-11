#!/usr/bin/env bash
# Regenerates frontend TypeScript types from the backend OpenAPI schema.
# Run after any backend API change. API types are generated, never hand written.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$ROOT/backend"
uv run python -c "import json; from app.main import app; print(json.dumps(app.openapi()))" \
  > "$ROOT/frontend/openapi.json"

cd "$ROOT/frontend"
npx openapi-typescript openapi.json -o src/lib/api-schema.d.ts
echo "generated frontend/src/lib/api-schema.d.ts"
