# Previewit: working agreement for Claude Code

Open-source peer-review platform for ANY organization (education is one preset). Read `docs/PLAN.md` and `docs/business/README.md` first.

## Architecture rules (enforced by `make layers`)
- Layers: `bootstrap` > `adapters` > `application` > `domain`. Imports only point downward.
- `domain/` and `application/` are pure Python: no FastAPI, Jinja2, SQLAlchemy, or I/O.
- The core is domain-neutral: say Space / Member / Party / Call / Submission / Review, never course / student / teacher. Education wording lives in presets.
- Words: use `docs/glossary.md` (ADR 0016). One concept, one word. Say anonymous, never blind; allocation, never assignment; Submission, never work product. `tests/unit/test_vocabulary.py` enforces it.
- A Party (user or group) is both author and reviewer. Never special-case direction.
- Identity display goes through one IdentityMask service (once built). Never render a name directly.
- Every tenant-owned row carries `org_id`.
- New artifact types, allocation strategies, etc. are plugins (`previewit.plugins`), never `if kind == "pdf"` in the core.

## Business rules (see `docs/business/`, ADR 0005)
- Hosted-first: the hosted site is the product. Optimise sign-up to first review round (target: under 10 minutes).
- Review by link is a core flow: request or give a review from a shared link with minimal sign-up.
- Free tier: 50 MB of storage and 100 shares per user. The organizer pays above that; students and reviewers never pay. Limits go through the `Entitlements` port, never `if plan == ...`.
- Year-1 scope: Education preset, text and PDF. No academic-venue features, code review or extra plugins.
- Self-hosting is expert-only and unsupported: Debian Linux (stable) and PostgreSQL. Do not add Docker, installers, other OS support or a small-server mode. Never make the code slower or heavier on purpose.
- Keep the developer setup easy (`make install`; SQLite for dev and tests).

## Workflow
- Test first: write the failing test, then the code. Domain logic gets unit tests (hypothesis where invariants exist).
- Each feature needs an acceptance scenario in `tests/acceptance` (Playwright, page-object style).
- Before finishing any task: `make check` must pass.
- Server returns HTML fragments (HTMX). No JSON APIs or SPA unless a plugin needs one. Keep JS tiny.
- Record notable decisions as ADRs in `docs/adr/`.

## Commands
Create GitHub milestones/issues: `scripts/bootstrap_github.sh --apply`.
`make install` · `make check` · `make unit` · `make integration` · `make acceptance` · `make run`
If Chromium cannot be downloaded: `make check PYTEST_ARGS="--browser-channel chrome"` (uses system Chrome).
