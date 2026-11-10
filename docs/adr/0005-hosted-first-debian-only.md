# ADR 0005: Hosted-first; self-hosting is Debian-only and unsupported
- Status: accepted
- Date: 2026-11-10
- Amends: ADR 0001 ("simple to self-host" is no longer a goal)

## Context
The business model is a hosted service with a free tier (50 MB of storage, 100 shares per user); the organizer pays above that. One founder works on the project two days a week. Effort spent on easy deployment competes with the hosted product.

## Decision
- The hosted service is the product. It must be much easier than running your own instance.
- Self-hosting stays possible under AGPL but is for experts and unsupported.
- One supported platform: Debian Linux (stable) with PostgreSQL. CI runs on Debian.
- No container image, installer, other operating systems or small-server mode.
- SQLite remains for local development and fast tests only.
- Difficulty comes from what we do not build. The code is never made slower or heavier on purpose; the hosted service runs the same code.

## Consequences
- Dockerfile removed.
- Contributor setup stays easy (`make install`, `make check`).
- Under AGPL anyone may publish their own installer or image; we neither block nor support it.
- Organizations that must self-host for data-residency reasons need their own operations skills.
