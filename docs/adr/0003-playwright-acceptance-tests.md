# ADR 0003: Playwright for acceptance tests
- Status: accepted
- Date: 2026-11-09

## Decision
Browser acceptance tests use Playwright (pytest-playwright) against a live uvicorn server started by a session fixture, via page objects.

## Consequences
Auto-waiting suits HTMX swaps. CI installs Chromium; where downloads are blocked, `--browser-channel chrome` uses a system Chrome.
