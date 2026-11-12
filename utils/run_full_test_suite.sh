#!/usr/bin/env bash
# Run the full Previewit test suite: lint, types, layering, unit, integration and
# browser acceptance tests (same as CI: `make check`).
#
# Usage:  utils/run_full_test_suite.sh
#         utils/run_full_test_suite.sh --report         # also write HTML/JUnit/coverage to reports/
#         utils/run_full_test_suite.sh --system-chrome  # use installed Chrome instead of downloading Chromium
#
# Works on macOS and Linux. Needs: uv, make, git.
set -euo pipefail

REPORT=0
CHROME=0
for arg in "$@"; do
  case "$arg" in
    --report) REPORT=1 ;;
    --system-chrome) CHROME=1 ;;
    -h|--help) sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) printf 'unknown option: %s (try --help)\n' "$arg" >&2; exit 2 ;;
  esac
done

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
say() { printf '\n==> %s\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

for tool in uv make git; do
  command -v "$tool" >/dev/null 2>&1 || die "'$tool' is required (macOS: brew install $tool; make comes with 'xcode-select --install')"
done

cd "$REPO_ROOT"

say "Installing dependencies (uv sync, including test tools)"
uv sync

export PYTEST_ARGS=""
if [ "$CHROME" -eq 1 ]; then
  PYTEST_ARGS="--browser-channel chrome"
else
  say "Installing Chromium for the acceptance tests"
  uv run playwright install chromium
fi

START=$(date +%s)
say "Running make check (lint, types, layering, all tests)"
if make check; then RESULT=0; else RESULT=$?; fi

if [ "$REPORT" -eq 1 ]; then
  say "Writing reports to reports/ (coverage, JUnit, HTML)"
  make report || printf 'warning: report generation failed\n' >&2
fi

ELAPSED=$(( $(date +%s) - START ))
if [ "$RESULT" -eq 0 ]; then
  say "PASS in ${ELAPSED}s"
else
  printf '\n==> FAIL (exit %s) after %ss\n' "$RESULT" "$ELAPSED" >&2
fi
exit "$RESULT"
