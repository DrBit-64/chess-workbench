#!/usr/bin/env bash
set -Eeuo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
service_pids=()

cleanup() {
  trap '' INT TERM
  printf '\n正在关闭前后端……\n'
  # Each service owns a process group, including make, uv, pnpm and their children.
  for service_pid in "${service_pids[@]}"; do
    kill -TERM -- "-$service_pid" 2>/dev/null || true
  done
  for service_pid in "${service_pids[@]}"; do
    wait "$service_pid" 2>/dev/null || true
  done
  printf '网站已关闭。\n'
}

if ! command -v setsid >/dev/null 2>&1; then
  printf '错误：需要 setsid（Linux / WSL2 的 util-linux 软件包）。\n' >&2
  exit 1
fi

cd "$project_root"
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

printf '正在启动 ChessWorkbench，按 Ctrl+C 同时关闭前后端。\n'
printf '网页地址：http://127.0.0.1:5173（等待下方 Vite 就绪提示）\n\n'

setsid make --no-print-directory dev-api &
service_pids+=("$!")
setsid make --no-print-directory dev-web DEV_WEB_ARGS=--strictPort &
service_pids+=("$!")

if wait -n "${service_pids[@]}"; then
  exit_code=0
else
  exit_code=$?
fi
printf '\n一个服务已退出，正在停止整个网站。\n'
exit "$exit_code"
