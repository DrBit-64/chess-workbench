#!/usr/bin/env bash
set -Eeuo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
smoke_directory="$(mktemp -d -t chess-workbench-smoke-XXXXXX)"
api_port="${CHESS_WORKBENCH_SMOKE_API_PORT:-18000}"
web_port="${CHESS_WORKBENCH_SMOKE_WEB_PORT:-14173}"
api_pid=""
web_pid=""

cleanup() {
  for process_id in "$web_pid" "$api_pid"; do
    if [[ -n "$process_id" ]]; then
      kill -TERM -- "-$process_id" 2>/dev/null || true
    fi
  done
  for process_id in "$web_pid" "$api_pid"; do
    if [[ -n "$process_id" ]]; then
      wait "$process_id" 2>/dev/null || true
    fi
  done
  rm -rf -- "$smoke_directory"
}
trap cleanup EXIT

cd "$project_root"

setsid env \
  CHESS_WORKBENCH_SERVICE_NAME="chess-workbench-api" \
  CHESS_WORKBENCH_VERSION="0.1.0" \
  CHESS_WORKBENCH_DATABASE_URL="sqlite+aiosqlite:///$smoke_directory/smoke.db" \
  CHESS_WORKBENCH_HOST="127.0.0.1" \
  CHESS_WORKBENCH_PORT="$api_port" \
  CHESS_WORKBENCH_DEBUG="false" \
  uv run --project backend --locked python -m chess_workbench \
  >"$smoke_directory/api.log" 2>&1 &
api_pid=$!

setsid env \
  CHESS_WORKBENCH_API_PROXY_TARGET="http://127.0.0.1:$api_port" \
  pnpm --dir frontend dev --host 127.0.0.1 --port "$web_port" --strictPort \
  >"$smoke_directory/web.log" 2>&1 &
web_pid=$!

if ! uv run --project backend --locked python scripts/assert_health.py \
  "http://127.0.0.1:$api_port/api/health" \
  "http://127.0.0.1:$web_port/api/health"; then
  echo "API log:"
  sed -n '1,240p' "$smoke_directory/api.log"
  echo "Frontend log:"
  sed -n '1,240p' "$smoke_directory/web.log"
  exit 1
fi

test -f "$smoke_directory/smoke.db"
echo "smoke test passed; direct API and Vite proxy both reached SQLite-backed health"
