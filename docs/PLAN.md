# Previewit — Project Plan

A fast, friendly, open-source peer-review system for **any organization** that wants work reviewed by peers: universities, journals and conferences, engineering teams, companies, NGOs, communities. Individuals review individuals, groups review individuals, individuals review groups, groups review groups. Reviewers comment directly on free text or PDFs and score against criteria. Other artifact types (code, Jira documentation, 3D models, video, …) arrive as plugins.

Education (students reviewing students) is the first *preset*, not a baked-in assumption. The core knows only Organizations, Spaces, Parties and Reviews.

Stack: Python · FastAPI · Jinja2 · HTMX · server-rendered, no SPA.

Business context and founder decisions: [`docs/business/`](business/README.md). Hosted-first and Debian-only: [ADR 0005](adr/0005-hosted-first-debian-only.md).

---

## 1. Principles

1. **Domain first.** Rules about reviews, groups, allocation and anonymity live in pure Python with no FastAPI, SQL or HTTP imports. They are unit-testable in milliseconds.
2. **Hexagonal (ports & adapters) modular monolith.** One deployable, strict internal boundaries. No microservices.
3. **Boundaries are enforced by tooling, not goodwill.** `import-linter` fails CI if `domain` imports `adapters`.
4. **Hypermedia over JSON.** The server returns HTML fragments; HTMX swaps them. JS is tiny, optional, progressive.
5. **Everything extensible is a plugin from day one**, including the built-in text and PDF types (we eat our own dog food).
6. **Tests before features.** Each milestone ends with passing unit, integration and acceptance tests.
7. **Fast is a feature with a budget** (see §7), checked in CI.
8. **Privacy by design.** Anonymity leaks (names in filenames, PDF metadata, URLs) are a tested requirement, not an afterthought. GDPR applies.

---

## 2. Domain model

Key idea: a **Party** is either a User or a Group. That one abstraction makes all four review directions work with no special cases.

```
Organization (tenant) ──< Member(user, org_role)
Organization ──< Space            # a course, a thesis seminar, a conference track, a journal issue, a team
Space ──< Membership(user, role: owner|chair|reviewer|author|participant)
Space ──< Group ──< GroupMembership(user)
Space ──< Call                    # an assignment / call for papers / review request
Call ──1 Rubric ──< Criterion
Call ──< Submission(author: Party, artifact)
Submission ──< Revision(n, artifact_version)          # same work, improved between rounds
Call ──< ReviewRound(n, opens, closes, targets_revision, anonymity_policy, allocation_strategy)
ReviewRound ──< ReviewTask(reviewer: Party, target: Submission, conflicts checked)
ReviewTask ──1 Review ──< CriterionScore(criterion, score, comment)
Review ──< Annotation(selector, body)
Submission ──< AuthorResponse(round, per-review reply)  # rebuttal / revision notes
Call ──< Decision(submission, outcome, by: chair)       # optional, for papers
```

| Concept | Notes |
|---|---|
| **Party** | `UserParty(user_id)` or `GroupParty(group_id)`. Used as submission author *and* reviewer. |
| **Artifact** | Content under review. Type-specific (`text`, `pdf`, later `code`, …) via plugin. Immutable versions, so annotations never drift. |
| **Annotation** | One model, polymorphic *selector* (W3C Web Annotation style): text = quote + offset; PDF = page + normalized rects; code = file + line range. |
| **Rubric / Criterion** | Reusable. Scale types: numeric, levels (e.g. 1–4 with descriptors), yes/no, free text. Optional weights. |
| **ReviewRound** | Deadline, target revision, `AnonymityPolicy`, allocation strategy, release rule. |
| **Group review** | One shared Review per reviewing group. Any member can edit (optimistic version check); each edit is attributed in an audit trail. Live co-editing is post-MVP. |
| **Allocation** | Pure function `(submissions, reviewers, constraints) → tasks`. Constraints: no self-review, no own group, N reviews each, balanced load. Strategies: random, round-robin, manual. |

### 2.1 Cardinality: 1:n and n:n

A `ReviewTask` links one reviewer **Party** to one **Submission**. Cardinality is entirely a matter of *allocation*:

| Pattern | Example |
|---|---|
| 1 → 1 | Student reviews one peer |
| 1 → n | Student reviews 3 peers; a teacher reviews all |
| n → 1 | 3 reviewers per paper |
| n → n | Every reviewer gets k submissions, every submission gets k reviewers |
| Group ↔ Group, Group ↔ Student, Student ↔ Group | Any Party on either side |

Nothing in the domain assumes one direction or a fixed ratio. Allocation strategies are pure functions, property-tested for invariants (no self/own-group review, no conflicts of interest, balanced load, exact review count).

### 2.2 Anonymity as a policy, not a mode

Instead of fixed modes, a round carries an `AnonymityPolicy` with independent directions:

- `author_visible_to_reviewer` (false → double-blind)
- `reviewer_visible_to_author` (false → single-blind, authors don't know reviewers)
- `reviewer_visible_to_other_reviewers`
- `reveal_after` (never / round close / decision)

This covers open, single-blind in **either** direction, and double-blind, with presets for each. A single **IdentityMask** service is the only code allowed to turn a Party into a display name, so every template and API goes through it. Pseudonyms are stable within a round ("Reviewer B") so discussions stay coherent. Leak tests cover filenames, PDF/Office metadata, URLs, timing and exports.

### 2.3 Rounds and revisions

A `Submission` has ordered `Revision`s. `ReviewRound n` targets a specific revision; reviewers in round 2 see the previous reviews, the author's response and a diff/changes summary (plugin-provided where the artifact type can diff). Rounds are unbounded (1, 2, 3, …). Annotations are pinned to a revision, so they never drift.

### 2.4 Academic papers (year-2 preset)

A `Space` can be configured as a venue (conference track or journal). That adds, as optional features rather than core assumptions:

- reviewer bidding / expertise tags and **conflict-of-interest** declarations used by allocation
- structured review forms (summary, strengths, weaknesses, confidence score)
- author response / rebuttal phase and chair **Decision** with notification
- BibTeX/DOI metadata on submissions

### 2.5 Domain-neutral core, presets on top

The core never says "student", "teacher" or "course". It uses **Space**, **Member**, **Party**, **Call**, **Submission**, **Review**. A **Preset** supplies vocabulary, default roles, rubric templates and workflow defaults:

| Preset | Space is a… | Roles | Typical defaults |
|---|---|---|---|
| Education | Course | teacher, assistant, student | Peer-to-peer, groups, single-blind, 2–3 reviews each |
| Academic venue | Conference track / journal | chair, reviewer, author | Double-blind, COI checks, rebuttal, decisions |
| Engineering team | Project / repo | lead, engineer | Open review, code/doc plugins, 1–2 reviewers |
| Company / generic | Team / programme | admin, member | Configurable |

Roles are data (named permission sets), not enum values in code. Labels come from the preset's translation catalogue, so an organization can rename anything ("Reviewer" → "Peer", "Call" → "Assignment").

### 2.6 Multi-tenancy and hosting

- `Organization` is the tenant. Every tenant-owned row carries `org_id`, enforced in the repository layer and tested (cross-tenant access tests are mandatory).
- **Hosted mode is the product:** many organizations, free tier with quotas. **Self-hosted mode:** single organization, no billing; expert-only and unsupported (Debian Linux, PostgreSQL; ADR 0005).
- An `Entitlements` port decides limits. Free tier: 50 MB of storage and 100 shares per user; the organizer pays above that; students and reviewers never pay. The domain asks "is this allowed?", never "which plan?". Billing (Stripe etc.) is an adapter, off by default.
- Per-tenant branding, per-tenant retention and data export/deletion for GDPR.

---

## 3. Architecture

```
previewit/
├─ src/previewit/
│  ├─ domain/          # entities, value objects, domain services. PURE PYTHON
│  ├─ application/     # use cases (commands/queries), ports (Protocols)
│  ├─ adapters/
│  │   ├─ web/         # FastAPI routers, Jinja2 templates, HTMX fragments, static
│  │   ├─ persistence/ # SQLAlchemy repos, Alembic migrations, unit of work
│  │   ├─ storage/     # file storage port: local FS now, S3 later
│  │   ├─ auth/        # local password (argon2) now; OIDC/LTI later
│  │   └─ notify/      # email, in-app
│  ├─ plugins/         # pluggy hookspecs + built-ins: text, pdf
│  └─ bootstrap.py     # composition root: wires adapters to ports
├─ tests/
│  ├─ unit/            # domain + application, in-memory fakes, no I/O
│  ├─ integration/     # repos vs real DB, routers via httpx
│  ├─ contract/        # one suite run against in-memory AND SQL adapters
│  └─ acceptance/      # Playwright, full browser
├─ docs/               # PLAN.md, ADRs, plugin guide
└─ pyproject.toml, CLAUDE.md, .github/
```

Dependency rule: `adapters → application → domain`. Never the reverse.

**Technology choices**

| Concern | Choice | Why |
|---|---|---|
| Packaging/env | `uv` | Fast, reproducible lockfile |
| DB | SQLAlchemy 2.0 + Alembic; PostgreSQL is the only supported production database; SQLite for local development and fast tests | Easy contributor setup, one production stack |
| Frontend | Jinja2 + HTMX + a little Alpine.js; hand-written CSS with design tokens (no Node build) | Lightning fast, zero JS toolchain for contributors |
| PDF | PDF.js for rendering; annotation layer in our own small JS module | Mature, open source |
| Text annotation | Server stores selectors; small JS captures the selection | Keeps JS minimal |
| Plugins | `pluggy` + Python entry points (`previewit.plugins`) | Standard, proven (pytest uses it) |
| Auth | Session cookie, argon2, CSRF tokens; `AuthProvider` port | OIDC/Shibboleth/Google later with no domain change |
| i18n | gettext/Babel from the start (EN + FI) | Cheap now, painful to retrofit |
| Quality | ruff, pyright (strict on `domain`), pre-commit, import-linter | |
| CI | GitHub Actions: lint → unit → integration → acceptance, coverage gate | |
| Deployment | Debian Linux (stable) only; no container image, no installer | Hosted-first (ADR 0005) |

**Plugin extension points (hookspecs)**
`ArtifactType` (ingest, render, annotation selector) · `AllocationStrategy` · `CriterionType` · `Exporter` · `Notifier` · `AuthProvider`.
The core never imports a plugin; it asks the registry. Plugin API is marked *unstable* until v0.2.

---

## 4. Design & UX

- **Look and feel:** inspired by Mentimeter's feel (big friendly type, generous whitespace, rounded cards, one strong accent colour, quick animated feedback). Own palette, name and assets, nothing copied.
- Design tokens (colour, spacing, radius, type scale) in one CSS file. Light and dark from the start.
- Key screens: space dashboard · "My reviews to do" (card per task, progress) · review workspace (artifact left, criteria + comments right, autosave) · "Feedback I received" · organizer setup wizard (call → rubric → round → allocate → release).
- Friendly by default (important for students, equally good for colleagues): friendly microcopy, rubric descriptors shown inline, "sentence starters" for constructive feedback, clear anonymity badge ("Your name is hidden").
- Accessibility: WCAG 2.2 AA, keyboard-complete review workspace, axe-core checks in acceptance tests.

---

## 5. Testing strategy

| Layer | Tooling | What it proves |
|---|---|---|
| **Unit** | pytest, in-memory fakes, `hypothesis` | Domain rules, allocation (property tests: nobody reviews self/own group, loads balanced), anonymity rules, scoring |
| **Contract** | pytest, parametrised over adapters | In-memory and SQL repos behave identically |
| **Integration** | pytest + httpx, real SQLite/Postgres | Routers, HTMX fragments, migrations, uploads, permissions |
| **Acceptance (E2E)** | **Playwright** (`pytest-playwright`) + optional `pytest-bdd` for Gherkin scenarios | Real user journeys in a real browser |
| **Non-functional** | axe-core in E2E, response-time assertions, Lighthouse CI | Accessibility and speed budgets |
| **Security** | Dedicated tests: authorisation matrix, anonymity-leak tests, CSRF | Nobody sees what they shouldn't |

**Selenium vs Playwright:** I recommend Playwright. It auto-waits (far fewer flaky tests, which matters with HTMX swaps), is faster, runs in parallel, has trace viewer and video on failure, and has first-class Python/pytest support. Selenium works fine if you prefer it; acceptance tests go through a thin page-object layer either way, so swapping is cheap.

**Acceptance scenarios (written first, one per milestone)**
1. Member A reviews Member B's text; B sees the feedback after release.
2. Group G reviews Member S's PDF with a comment anchored to page 2.
3. Member reviews a group's submission under double-blind; no identity appears anywhere.
4. Organizer creates a rubric, allocates 3 reviews each, and no one gets themselves or their own group.
5. Round 2: author submits a revision with a response; reviewers see the earlier reviews and the changes.
6. Paper flow: 3 reviewers per paper, conflicts respected, chair records a decision.

---

## 6. Roadmap

**Status:** M0 done (licence: AGPL-3.0-or-later) (walking skeleton, tooling, CI, ADRs, `Party` and `AnonymityPolicy` domain with unit tests, Playwright test). Login (Google, Apple, HAKA, email + password) is implemented ahead of M1 (see ADR 0007). Organizations, spaces, roles (preset-defined), invite links and groups are implemented (ADR 0009); M1 is done (authorisation matrix and cross-tenant tests pass). Next: M2.

Every milestone: small PRs, tests first, CI green, ADR for each notable decision.

| # | Milestone | Deliverables | Exit criteria |
|---|---|---|---|
| **M0** | **Foundations & walking skeleton** | Repo, `pyproject`, ruff/pyright/import-linter, pre-commit, CI, CLAUDE.md, ADR template, design tokens, base layout, "hello" page via HTMX, one Playwright test in CI, LICENSE/CONTRIBUTING/CoC | Empty app deploys; E2E test runs in CI; layering rule enforced |
| **M1** | Organizations, identity, spaces, groups | Org (tenant) + isolation tests, sign-up/login, data-driven roles, space create/join (invite), groups CRUD, preset mechanism with Education preset | Authorisation matrix and cross-tenant tests pass |
| **M2** | Calls, submissions & revisions | Call CRUD, `ArtifactType` plugin API, built-in **text** and **PDF** types, versioned artifacts, revisions, Party-authored submissions, **review by link** (share a call or a submission; minimal sign-up) | Individual and group submissions work E2E |
| **M3** | Rubrics | Criteria builder, scale types, reusable rubrics | Rubric renders in review form |
| **M4** | Review rounds & allocation | Multi-round config, 1:n / n:n allocation (random, round-robin, manual), property tests | Allocation invariants hold for random inputs |
| **M5** | Review workspace | Criteria form with autosave, text annotations, PDF annotations, group-shared review editing | Acceptance scenarios 1 and 2 pass |
| **M6** | Anonymity, release & feedback | Directional `AnonymityPolicy` + `IdentityMask`, release rules, "feedback received", author responses, later-round view, notifications, leak tests | Scenario 3 passes; leak tests pass |
| **M7** | Polish & v0.1 | Performance pass, a11y audit, EN/FI strings, docs, seed demo data, organizer export (CSV) | Budgets met; **v0.1.0 tagged** |
| **M8** | Hosted service | Multi-tenant hosted mode, `Entitlements` port with storage and share quotas, usage display and upgrade prompt, payment adapter, abuse controls (rate limits, upload checks, takedown), terms and privacy pages | A stranger signs up and runs a round unaided; quotas enforced and tested |
| **M9** | Moodle via LTI 1.3 | LTI 1.3 launch, roster and grade return, sign-in from the LMS | A Moodle course launches a call and receives grades |

**After M9 (year 2):** stabilise plugin API (v0.2) and a first non-document plugin → Academic-venue preset (bidding, COI, rebuttal, decisions) → OIDC/Shibboleth/SAML → code-review plugin (line comments, Git import) → external-reference artifacts (Jira, Confluence, Figma, Blender, video) → review-of-review → analytics → live group co-editing (SSE) → AI-assisted feedback hints (opt-in).

---

## 7. Performance budgets (checked in CI)

- Server response p95 < 100 ms for page loads on seeded data
- HTML fragment swaps < 50 ms server-side
- JS shipped < 50 KB gzipped (excluding PDF.js, lazy-loaded only on PDF pages)
- Fonts self-hosted; no third-party requests
- Gzip/Brotli, ETags, indexed queries, no N+1 (assert query counts in integration tests)

---

## 8. Security & privacy

- Authorisation in the application layer, tested as a role × resource matrix
- Uploads: size and type limits, content sniffing, stored outside web root under random IDs
- Reviewer-facing artifacts are stripped of PDF/document metadata in blind modes
- CSRF tokens, secure cookies, rate limiting on auth, argon2 password hashes
- GDPR: data export and deletion per user, retention settings per organization and space, audit log

---

## 9. Open-source & workflow

- **Licence (your decision):** with a freemium hosted offering, **AGPL-3.0** (optionally dual-licensed commercially) stops competitors from running a closed hosted fork, while organizations can still self-host freely. Apache-2.0 / MIT maximise adoption but allow closed hosted forks. **Decision: AGPL-3.0-or-later.** Note: a later commercial dual licence needs contributors to grant relicensing rights (a CLA); DCO sign-off alone does not, so decide on a CLA before accepting outside contributions you may want to relicense.
- Conventional commits, trunk-based with short-lived branches, required CI to merge
- Issue/PR templates, `good first issue` labels, plugin author guide, ADRs in `docs/adr/`
- **Claude Code setup:** `CLAUDE.md` holding the dependency rule, test-first rule, commands (`uv run pytest`, `ruff`, `playwright`), and "never import adapters from domain". Work milestone by milestone: ask for the failing test first, then the implementation.

---

## 10. Assumptions to confirm

1. Name/package: `previewit`.
2. SQLite for local development and tests only; PostgreSQL is the only supported production database.
3. Local accounts plus Google, Apple and HAKA login were pulled forward (ADR 0007); organizations and roles remain in M1.
4. English + Finnish UI; vocabulary overridable per organization.
5. Group review = one shared review editable by any member (no live co-editing yet).
6. Default anonymity = reviewer hidden from author, configurable per round and direction.
7. Target scale: the hosted service with many tenants. Self-hosting is not sized for small servers.
8. Plain CSS with design tokens in M0 (no Tailwind/Node); revisit if CSS grows unwieldy.
9. Hosted multi-tenant, quotas and billing arrive in M8, but `org_id` is in the schema from M1. Self-hosted = single organization, Debian only, unsupported.
