# ADR 0002: Server-rendered HTML with HTMX, plain CSS tokens
- Status: accepted
- Date: 2026-11-09

## Context
Goal: lightning-fast, accessible UI, low contributor barrier, no JS build chain.

## Decision
Jinja2 templates return pages and fragments; HTMX swaps them. htmx is vendored (no CDN). Styling is hand-written CSS driven by design tokens; system font stack.

## Consequences
Tiny JS payload, no Node toolchain. Rich widgets (PDF annotation) are isolated JS modules loaded only where needed.
