# ADR 0006: Organizations and networks as parties are deferred
- Status: proposed
- Date: 2026-11-10

## Context
The vision includes peer review among individuals, organizations and networks of organizations. Today a `Party` is a `UserParty` or a `GroupParty`, both inside one Space of one Organization (tenant). Year 1 targets education, where individuals and groups are enough.

## Decision
Do not add an organization-level party in year 1. Keep `Party` a closed union handled by exhaustive `match`, so adding `OrgParty` later is a type-checked change. Do not assume in new code that author and reviewer belong to the same Organization where it costs nothing to avoid.

## Consequences
- Cross-organization review needs later work on tenancy (a review that spans tenants), identity masking and quotas (who pays).
- Revisit when the first network or consortium pilot is planned.
