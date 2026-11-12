# 0010. Configuration file and verification policy

Status: accepted

## Context
Settings were environment variables only. Operators need one reviewable file, and the decision "which actions require a verified email" is an operator policy, not code.

## Decision
- Optional TOML file (stdlib `tomllib`): `PREVIEWIT_CONFIG`, else `./previewit.toml`, else `/etc/previewit/previewit.toml`. Environment variables override the file.
- Strict: unknown sections, keys, actions and wrong types are startup errors. A typo must never silently weaken a policy.
- Secrets may be inline or read from a file; relative paths resolve against the config file; a group/world-readable file holding secrets logs a warning.
- Domain `Action` enum and `VerificationPolicy(required_for)`. Default: only `review` needs a verified email (unverified users may be invited, join and submit). Replaces `User.can_review`.
- `TenancyService` enforces `create_organization`, `invite` and `join` (`VerificationRequired` → 403 page linking to the account page). `submit` and `review` are enforced where those actions exist (M2).

## Consequences
One place to read the deployment's behaviour. The policy is global per deployment; per-organization policy can come later without changing the domain type.
