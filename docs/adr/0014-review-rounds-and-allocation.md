# 0014. Review rounds and allocation

Status: accepted

## Context
A call needs one or more rounds of review. Who reviews what must respect "not yourself, not your own group", work for individuals and groups on either side, and be explainable and testable. The PLAN lists random, round-robin and manual allocation and anonymity as a per-round choice.

## Decision
- A **ReviewRound** belongs to a call, is numbered 1, 2, 3 ... (unique per call, enforced by the database), and records `per_submission`, its allocation strategy, an anonymity preset, and an optional open and close time. Status (scheduled, open, closed) is computed from the clock, never stored.
- A **ReviewTask** pairs one reviewer Party with one submission and the revision number that was latest when it was made. Both sides are Parties, so person to group, group to person and group to group need no special code. Rows carry `org_id`; composite foreign keys tie tasks to their round and submission within the same organization.
- **Allocation is a pure domain function** (`domain/allocation.py`). A reviewer and an author are `Slot`s holding the set of people behind them; two slots conflict when the sets overlap. This one rule covers self-review and own-group review in every direction. Organizers or later features (declared conflicts of interest) can add pairs.
- The core greedy step gives every submission its reviewers from those with the fewest reviews so far, serving the most constrained submissions first. A repair pass then moves reviews along chains of reviewers until no chain evens the load further, so with only authorship conflicts the loads differ by at most one. If there are too few eligible reviewers, each submission gets all it can and the gap is reported, never hidden.
- **Strategies are plugins** (`AllocationStrategy`, same entry-point group as artifact and criterion types): `random` (seeded shuffle), `round_robin` (fixed rotation), `manual` (no automatic pairs; the organizer adds and removes tasks, with the same conflict and duplicate checks).
- In peer review the **authors are the reviewers**. Pairing someone outside the authors (for example the teacher) is done by hand.
- New permission `rounds.manage` (owner, teacher). Students see only their own tasks ("My reviews"), only for published calls and only once a round has opened. Task listings do not name the author: who may see whom is the anonymity policy's job in M6 (IdentityMask). The organizer's page shows everyone.
- The anonymity preset is only recorded in M4; M6 applies it.

## Consequences
Allocating again replaces every task of the round. **Open for M5:** once reviews exist, re-allocation and task removal must refuse (or keep) tasks that already have a review, and a revision published after allocation does not change which revision a task points at. Round 2 allocates against the then-latest revisions. Large classes are fine: allocating 600 people with three reviews each takes well under a second.
