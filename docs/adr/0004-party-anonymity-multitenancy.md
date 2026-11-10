# ADR 0004: Party abstraction, directional anonymity, tenant-aware from day one
- Status: accepted
- Date: 2026-11-09

## Decision
Authors and reviewers are Parties (user or group), giving 1:n and n:n in every direction. Anonymity is an `AnonymityPolicy` with independent directions plus reveal timing. All tenant-owned data carries `org_id`. The core is domain-neutral; presets supply vocabulary and defaults.

## Consequences
Single-blind in either direction, double-blind and open share one code path. Hosted multi-tenant mode needs no schema rewrite.
