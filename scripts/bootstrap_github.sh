#!/usr/bin/env bash
# Creates labels, milestones (M1-M7) and starter issues in the current GitHub repo.
# Requires: gh (authenticated) and a repo remote. Dry run by default; pass --apply to create.
set -euo pipefail
APPLY=0; [[ "${1:-}" == "--apply" ]] && APPLY=1
run() { if (( APPLY )); then "$@"; else printf 'DRY: %q ' "$@"; echo; fi; }

milestone() { run gh api repos/:owner/:repo/milestones -f title="$1" -f description="$2" >/dev/null; }
issue() { run gh issue create --milestone "$1" --label "$2" --title "$3" --body "$4"; }

for l in "domain:0e8a16" "adapter:1d76db" "plugin:5319e7" "ux:fbca04" "security:d93f0b" "testing:c5def5" "docs:0075ca"; do
  run gh label create "${l%%:*}" --color "${l##*:}" --force
done

M1="M1 Organizations, identity, spaces, groups"
M2="M2 Calls, submissions and revisions"
M3="M3 Rubrics"
M4="M4 Review rounds and allocation"
M5="M5 Review workspace"
M6="M6 Anonymity, release and feedback"
M7="M7 Polish and v0.1"
milestone "$M1" "Tenant isolation, auth, data-driven roles, spaces, groups, Education preset"
milestone "$M2" "Call CRUD, ArtifactType plugin API, text and PDF types, revisions"
milestone "$M3" "Criteria builder and scale types"
milestone "$M4" "Multi-round config and 1:n / n:n allocation with property tests"
milestone "$M5" "Criteria form, text and PDF annotations, group-shared reviews"
milestone "$M6" "Directional anonymity, IdentityMask, release, author responses"
milestone "$M7" "Performance, accessibility, i18n EN/FI, docs, v0.1.0"

issue "$M1" domain "Organization (tenant) entity and repository-level org_id enforcement" "Every tenant-owned row carries org_id. Add cross-tenant access tests that must fail closed. See docs/PLAN.md section 2.6."
issue "$M1" adapter "Persistence: SQLAlchemy 2.0 + Alembic, SQLite (WAL) and PostgreSQL, unit of work" "Add contract tests run against in-memory and SQL repositories."
issue "$M1" security "Local accounts: sign-up, login, session cookie, argon2, CSRF" "Behind an AuthProvider port so OIDC/SAML can be added later. Add rate limiting on auth endpoints."
issue "$M1" domain "Data-driven roles and permissions (role = named permission set)" "No role enums in core code. Add an authorisation matrix test (role x resource)."
issue "$M1" domain "Spaces, invite links, and groups (CRUD, membership)" "Core vocabulary only: Space, Member, Party."
issue "$M1" ux "Preset mechanism and Education preset (vocabulary, default roles)" "Labels come from a per-preset catalogue that an organization can override."
issue "$M2" plugin "ArtifactType plugin API (pluggy) and registry" "Core never imports a plugin directly. Mark API unstable. Add a plugin author guide stub."
issue "$M2" plugin "Built-in text artifact type" "Immutable versions; render and annotation selector (quote + offset)."
issue "$M2" plugin "Built-in PDF artifact type" "Upload validation, metadata stripping, PDF.js viewer loaded only on PDF pages."
issue "$M2" domain "Submissions authored by a Party (user or group) with ordered Revisions" "Acceptance: individual and group submissions."
issue "$M3" domain "Rubric and Criterion with scale types (numeric, levels, yes/no, text) and weights" "Reusable across calls."
issue "$M4" domain "ReviewRound with AnonymityPolicy, target revision, deadlines" "AnonymityPolicy already exists in domain/anonymity.py."
issue "$M4" domain "Allocation strategies: random, round-robin, manual (pure functions)" "Hypothesis property tests: no self/own-group review, exact counts, balanced load."
issue "$M4" domain "Conflict-of-interest constraints in allocation" "Needed for the academic-venue preset."
issue "$M5" ux "Review workspace layout: artifact left, criteria and comments right, autosave" "HTMX; keyboard-complete; WCAG 2.2 AA."
issue "$M5" ux "Text annotations (select text, comment)" "Selector = quote + offset, pinned to a revision."
issue "$M5" ux "PDF annotations (page + normalised rectangles)" "Isolated JS module."
issue "$M5" domain "Group-shared review with optimistic version check and audit trail" "Any member can edit; edits are attributed."
issue "$M6" security "IdentityMask service: the only code that turns a Party into a display name" "Stable pseudonyms per round. Add CI test that templates never render names directly."
issue "$M6" testing "Anonymity leak tests: filenames, PDF metadata, URLs, timing, exports" "Run for every AnonymityPolicy preset."
issue "$M6" domain "Author responses and later-round view (previous reviews + changes)" "Acceptance: round 2 scenario in docs/PLAN.md."
issue "$M7" testing "Performance budgets in CI (p95 < 100 ms, JS < 50 KB gz, query-count assertions)" "See docs/PLAN.md section 7."
issue "$M7" docs "i18n (EN + FI), seed demo data, user and plugin docs, tag v0.1.0" ""
