# 0011. Calls, submissions, revisions and review by link

Status: accepted

## Context
M2 needs work to be asked for (calls), answered (submissions by a Party), improved between rounds (revisions) and shown to people outside the space (review by link), for text and PDF in year 1, without hard-wiring those two types.

## Decision
- **Call** belongs to a Space (`org_id` carried, composite FK). It names an artifact type, may require group work, may have a deadline (UTC) and is published or draft. Type and group mode are fixed at creation. A call with submissions cannot be deleted; unpublish it.
- **Submission**: one per author Party per call (database-unique). Individual calls: `UserParty`; group calls: `GroupParty` of a group you belong to. Anyone in the group can add revisions; leaving the group ends access.
- **Revision**: append-only and numbered 1, 2, 3 without gaps, so annotations in M5 can pin to one. Content is stored in the database for now (10 MB PDF limit, 400 kB text); a blob store comes with the quotas in M8.
- **Visibility**: authors, and staff with `submissions.view_all`. Peers get 404, not 403. New permissions: `calls.manage`, `submissions.create`, `submissions.view_all`.
- **ArtifactType plugin API** (`application/artifacts.py`): `ingest` and `render_html`, discovered through the `previewit.plugins` entry-point group. Text and PDF are ordinary plugins. See `docs/plugins/artifact-types.md`.
- **Review by link**: a share link (256-bit secret, SHA-256 stored, expiry, revocable, shown once) for one call or one submission. Opening it needs an account (name, email, password, or Google/Apple) and records a grant to that one target. It never makes the visitor a member of the space. Existing grants survive revocation of the link. Writing reviews arrives in M5, where the `review` verification policy applies.
- **Policy**: `submit` gates submit and revise; `invite` gates creating share links. Viewing through a link is never gated.
- **Entitlements** port with an unlimited default adapter; the share-link quota (100 per user on the free tier) is wired through it and becomes real in M8.

## Consequences
Content in the database makes backups simple and is fine at this scale. Upload size is limited by `Content-Length` before the body is read; a reverse proxy should enforce the same limit.
