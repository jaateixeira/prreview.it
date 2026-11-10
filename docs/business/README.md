# Previewit — Business docs

**Mission:** make peer review easy.
**Product:** open-source (AGPL-3.0) peer-review platform. Any artifact via plugins (text, PDF, code, 3D, video, patents…). Any party: individuals, groups, organisations, networks of organisations.
**Entry point:** anyone sends something for review with a link at `peereview.it`.
**Beachhead:** education, integrated with Moodle. **Ambition:** born global.

| Folder | Doc | Content |
|---|---|---|
| `market/` | `market-analysis.md` | Problem, trends, segments, sizing |
| `market/` | `competitors.md` | Competitor table, positioning map and statement |
| `strategy/` | `strategy.md` | Where to play, how to win, pricing, risks |
| `strategy/` | `business-model-canvas.md` | The nine blocks + value/money flow |
| `plan/` | `year-1-plan.md` | Nov 2026 – Oct 2027 roadmap, KPIs, capacity |

Technical plan lives in `docs/PLAN.md`.

## Founder decisions (2026-11-10)

| Topic | Decision |
|---|---|
| Capacity | Solo founder, 2 days a week, as a side activity in free time |
| Funding | None external; bootstrapped |
| Pricing | Free tier: under 50 MB of storage and up to 100 shares per user. Students and reviewers never pay. The organiser of the review pays. |
| Deployment | Hosted site is the easy path and free to start. Self-hosting stays open (AGPL) but is expert-only by design: Debian Linux only, strong technical skills and good hardware required. |
| First pilot | Founder's own courses |
| Domain | To be registered as soon as possible |

## What this means for the code roadmap

These business choices set the priorities in `docs/PLAN.md`:

1. **Hosted-first.** The hosted site is the main product. Sign-up to first review round in minutes.
   **Self-hosting is expert-only:** Debian Linux only, production stack only (PostgreSQL, no small-server mode), no installer, no container image, no support. Do not spend effort making deployment easy.
2. **Review-by-link is a new capability** and comes before LTI: request or give a review from a shared link with minimal sign-up. A teacher can paste the link into a Moodle course without asking a Moodle admin.
3. **Two quotas** are the entitlements that matter: storage (50 MB) and shares (100 per user), each with usage display and upgrade prompt. They replace plan-by-feature limits.
4. **LTI 1.3 follows** once link-based use is proven (grades back to Moodle, single sign-on).
5. **One non-document plugin** as proof of "review anything", early in year 2.

## Open questions

1. Exact name and domain before registering: `peereview.it` (used in these docs), `prreview.it` (this repository), `peerreview.it` or `previewit.*`?
2. Is the 50 MB limit per organiser account (assumed here) or per review call?
3. What counts as a share, and is 100 a lifetime or a monthly limit? Assumed: one artifact sent for review by link, lifetime, counted against the user who starts it; submissions inside an organiser's call count against the organiser.
4. Price above the free limits: the tiers in `strategy.md` are placeholders.
