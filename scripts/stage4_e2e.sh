#!/usr/bin/env bash
set -Eeuo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
e2e_directory="$(mktemp -d -t chess-workbench-stage4-XXXXXX)"
api_port="${CHESS_WORKBENCH_E2E_API_PORT:-18700}"
web_port="${CHESS_WORKBENCH_E2E_WEB_PORT:-15173}"
api_pid=""
web_pid=""

if command -v pnpm >/dev/null 2>&1; then
  pnpm_command=(pnpm)
elif command -v corepack >/dev/null 2>&1; then
  pnpm_command=(corepack pnpm)
else
  echo "error: pnpm or corepack is required" >&2
  exit 127
fi

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
  rm -rf -- "$e2e_directory"
}
trap cleanup EXIT

cd "$project_root"
export CHESS_WORKBENCH_DATABASE_URL="sqlite+aiosqlite:///$e2e_directory/stage4.db"
export CHESS_WORKBENCH_SOURCE_STORAGE_ROOT="$e2e_directory/data"

uv run --project backend --locked alembic -c backend/alembic.ini upgrade head \
  >"$e2e_directory/migration.log" 2>&1

setsid env \
  CHESS_WORKBENCH_SERVICE_NAME="chess-workbench-api" \
  CHESS_WORKBENCH_VERSION="0.1.0" \
  CHESS_WORKBENCH_HOST="127.0.0.1" \
  CHESS_WORKBENCH_PORT="$api_port" \
  CHESS_WORKBENCH_DEBUG="false" \
  uv run --project backend --locked python -m chess_workbench \
  >"$e2e_directory/api.log" 2>&1 &
api_pid=$!

setsid env \
  CHESS_WORKBENCH_API_PROXY_TARGET="http://127.0.0.1:$api_port" \
  "${pnpm_command[@]}" --dir frontend dev --host 127.0.0.1 --port "$web_port" --strictPort \
  >"$e2e_directory/web.log" 2>&1 &
web_pid=$!

if ! uv run --project backend --locked python scripts/assert_health.py \
  "http://127.0.0.1:$api_port/api/health" \
  "http://127.0.0.1:$web_port/api/health"; then
  sed -n '1,240p' "$e2e_directory/api.log"
  sed -n '1,240p' "$e2e_directory/web.log"
  exit 1
fi

set +e
CHESS_WORKBENCH_E2E_BASE_URL="http://127.0.0.1:$web_port" \
  "${pnpm_command[@]}" --dir frontend e2e
test_rc=$?
set -e
if [[ "$test_rc" -ne 0 ]]; then
  echo "Stage 4 API log:"
  sed -n '1,240p' "$e2e_directory/api.log"
  echo "Stage 4 frontend log:"
  sed -n '1,240p' "$e2e_directory/web.log"
fi
exit "$test_rc"
