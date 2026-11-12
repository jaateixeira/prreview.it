#!/usr/bin/env bash
# Run Previewit locally on macOS for manual testing (runtime dependencies only).
#
# Usage:  utils/run_mac.sh            # http://127.0.0.1:8000
#         PORT=8010 utils/run_mac.sh
#         NO_OPEN=1 utils/run_mac.sh  # do not open the browser
#
# Needs: Homebrew (https://brew.sh). Installs uv and git if missing.
set -euo pipefail

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
URL="http://${HOST}:${PORT}"

say() { printf '\n==> %s\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

[ "$(uname -s)" = "Darwin" ] || printf 'warning: this script is written for macOS (found %s); continuing.\n' "$(uname -s)" >&2

# Tools
for tool in git uv; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    command -v brew >/dev/null 2>&1 || die "'$tool' is missing and Homebrew is not installed. See https://brew.sh"
    say "Installing $tool with Homebrew"
    brew install "$tool"
  fi
done

# Port must be free
if command -v lsof >/dev/null 2>&1 && lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  die "port $PORT is already in use. Try: PORT=8010 $0"
fi

cd "$REPO_ROOT"

say "Installing dependencies (uv sync --no-dev)"
uv sync --no-dev

say "Starting Previewit on $URL (Ctrl+C to stop)"
uv run --no-dev uvicorn previewit.bootstrap:create_app --factory --host "$HOST" --port "$PORT" &
SERVER_PID=$!
trap 'kill "$SERVER_PID" 2>/dev/null || true; wait "$SERVER_PID" 2>/dev/null || true; printf "\nStopped.\n"' EXIT INT TERM

# Wait up to 30 s for the health check
for _ in $(seq 1 60); do
  if curl -fsS "$URL/healthz" >/dev/null 2>&1; then
    say "Healthy: $URL/healthz answered ok"
    break
  fi
  kill -0 "$SERVER_PID" 2>/dev/null || die "server exited during startup (see output above)"
  sleep 0.5
done
curl -fsS "$URL/healthz" >/dev/null 2>&1 || die "server did not become healthy within 30 seconds"

if [ -z "${NO_OPEN:-}" ] && command -v open >/dev/null 2>&1; then
  open "$URL"
fi

wait "$SERVER_PID"
