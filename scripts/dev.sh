#!/usr/bin/env bash
# Start the local engine API (real MuJoCo, :8000) and the web dev server (:5173) together; Ctrl-C stops both.
#   scripts/dev.sh            # engine + web
#   ENGINE_PORT=8001 scripts/dev.sh   (the web app expects :8000 unless you change ENGINE_API in apps/web/src/bundle.ts)
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENGINE_PORT="${ENGINE_PORT:-8000}"
UVICORN="$ROOT/packages/engine/.venv/bin/uvicorn"
if [ ! -x "$UVICORN" ]; then
  echo "engine venv missing: create it with: cd $ROOT/packages/engine && uv venv && uv pip install -e . -e ../core" >&2
  exit 1
fi
if [ ! -d "$ROOT/apps/web/node_modules" ]; then (cd "$ROOT/apps/web" && pnpm install); fi
pids=()
cleanup() { trap - INT TERM EXIT; for p in "${pids[@]}"; do kill "$p" 2>/dev/null || true; done; wait 2>/dev/null || true; }
trap cleanup INT TERM EXIT
(cd "$ROOT/packages/engine" && exec "$UVICORN" kinetra_engine.api:app --port "$ENGINE_PORT") &
pids+=($!)
(cd "$ROOT/apps/web" && exec pnpm dev) &
pids+=($!)
echo "engine: http://localhost:$ENGINE_PORT/health   web: http://localhost:5173  (Live tab = real MuJoCo)"
wait -n
