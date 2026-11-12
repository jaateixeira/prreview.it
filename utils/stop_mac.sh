#!/usr/bin/env bash
# Stop the local Previewit server on macOS. Does not start, pull or change anything.
#
# Usage:  utils/stop_mac.sh              # stop whatever listens on port 8000
#         PORT=8010 utils/stop_mac.sh    # another port
#         utils/stop_mac.sh --list       # show what is listening, stop nothing
#         utils/stop_mac.sh --force      # SIGKILL at once, no grace period
#         TIMEOUT=30 utils/stop_mac.sh   # seconds to wait before forcing (default 10)
#
# Exit codes: 0 stopped (or nothing running), 1 could not stop it, 2 bad usage.
set -euo pipefail

PORT="${PORT:-8000}"
TIMEOUT="${TIMEOUT:-10}"
MODE="stop"
FORCE=0

for arg in "$@"; do
  case "$arg" in
    --list) MODE="list" ;;
    --force) FORCE=1 ;;
    -h|--help) sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) printf 'unknown option: %s (try --help)\n' "$arg" >&2; exit 2 ;;
  esac
done

say() { printf '==> %s\n' "$*"; }

if ! command -v lsof >/dev/null 2>&1; then
  printf 'error: lsof is required (it ships with macOS)\n' >&2
  exit 1
fi

# PIDs of processes LISTENING on the port (server side only, not browser clients)
listeners() { lsof -nP -tiTCP:"$PORT" -sTCP:LISTEN 2>/dev/null || true; }

pids="$(listeners)"
if [ -z "$pids" ]; then
  say "Nothing is listening on port $PORT"
  exit 0
fi

if [ "$MODE" = "list" ]; then
  lsof -nP -iTCP:"$PORT" -sTCP:LISTEN
  exit 0
fi

say "Listening on port $PORT:"
lsof -nP -iTCP:"$PORT" -sTCP:LISTEN | sed 's/^/    /'

if [ "$FORCE" -eq 1 ]; then
  say "Sending SIGKILL to pid(s): $(echo $pids)"
  kill -9 $pids 2>/dev/null || true
else
  say "Sending SIGTERM to pid(s): $(echo $pids)"
  kill $pids 2>/dev/null || true
  waited=0
  while [ -n "$(listeners)" ] && [ "$waited" -lt "$TIMEOUT" ]; do
    sleep 1
    waited=$((waited + 1))
  done
  if [ -n "$(listeners)" ]; then
    say "Still running after ${TIMEOUT} s; sending SIGKILL"
    kill -9 $(listeners) 2>/dev/null || true
    sleep 1
  fi
fi

if [ -n "$(listeners)" ]; then
  printf 'error: port %s is still in use (pid %s)\n' "$PORT" "$(listeners)" >&2
  exit 1
fi
say "Stopped. Port $PORT is free."
