# ADR 0001: Hexagonal modular monolith
- Status: accepted
- Date: 2026-11-09

## Context
The system must grow plugins, multiple hosting modes, and many artifact types, while staying fast to run and simple to self-host.

## Decision
One deployable. Layers `bootstrap > adapters > application > domain`, enforced by import-linter. Domain and application are framework-free.

## Consequences
Domain tests run in milliseconds; adapters (DB, storage, auth) are swappable; CI fails on layering violations.
