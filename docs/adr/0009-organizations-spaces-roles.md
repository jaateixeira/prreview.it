# ADR 0009: Organizations, spaces, roles and invite links
- Status: accepted
- Date: 2026-11-12

## Context
M1 needs tenants, a place where a round happens (a space: a course in the Education preset), people with roles in it, groups, and a fast way to get participants in (hosted-first, review by link).

## Decision
- **Organization = tenant.** Any user can create one and becomes its owner. Owners have every permission in every space of the organization. Joining a space by link makes you a plain organization member.
- **Space belongs to one organization.** Created by an owner; the creator gets the preset's creator role.
- **Roles are data supplied by presets** (`domain/tenancy.py`). A role is a key, a label and a set of permissions. The core only knows permissions (`space.view`, `space.manage`, `members.invite`, `members.manage`, `groups.manage`). The Education preset defines teacher, teaching assistant and student and the vocabulary (course, participant...). Presets are plain data, so adding one needs no core change.
- **No privilege escalation.** You may grant (via invite or role change) only roles whose permissions are a subset of yours. You cannot change your own role or remove yourself, and cannot act on someone stronger than you.
- **Outsiders get "not found", never "forbidden".** Someone with no view permission in a space cannot tell it exists. Members who lack a permission get "forbidden".
- **Invite links**: 256-bit secret, only its SHA-256 stored, expiry (default 7 days, at most 90), optional maximum uses, revocable. The secret is shown once, at creation. Using a link is one conditional UPDATE, so concurrent joins cannot exceed the limit. Someone already in the space is sent there without using a seat and is never demoted, even if the link is spent.
- **Tenant isolation in the schema.** Every tenant-owned table has `org_id`. Child rows reference their parent with a composite foreign key `(space_id, org_id)`, so a row cannot name a different tenant than its parent. SQLite enforces foreign keys through `make_engine`.
- **Member lists** show display names to everyone in the space and email addresses only to people who may manage members.
- **Review gate (decision):** unverified users may be invited, join, and submit, but cannot review. This is `User.can_review`; the review milestone enforces it.

## Consequences
- Groups are per space and list members; a group is addressable as a `GroupParty` once calls and submissions exist (M2).
- Per-organization custom roles are possible later by storing role definitions instead of reading them from the preset.
- Quotas and who pays arrive with `Entitlements` (M8); there is no limit on organizations or spaces yet.
- Leaving a space, transferring ownership, and organization-level member management are not built.
