"""Allocation: who reviews what. A pure function, no I/O, no knowledge of artifacts.

A *reviewer* and an *author* are both Parties; each carries the set of people behind it
(one person, or a group's members). Two Parties conflict when those sets overlap, which
covers "not yourself" and "not your own group" in every direction (person to group, group
to person, group to group) with one rule. Organizers can add extra conflicts (for example
declared conflicts of interest).
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Slot:
    """One side of a pairing: a stable key plus the people behind it."""

    key: str
    people: frozenset[str]


@dataclass(frozen=True)
class Problem:
    reviewers: Sequence[Slot]
    submissions: Sequence[Slot]  # the slot of a submission is its author
    per_submission: int  # how many reviews each submission should get
    extra_conflicts: frozenset[tuple[str, str]] = frozenset()  # (reviewer key, submission key)
    existing: frozenset[tuple[str, str]] = frozenset()  # pairs that must not be repeated


@dataclass(frozen=True)
class Allocation:
    pairs: tuple[tuple[str, str], ...]  # (reviewer key, submission key)
    shortfall: dict[str, int] = field(default_factory=dict[str, int])  # submission key -> missing


def conflicts(reviewer: Slot, author: Slot, extra: Collection[tuple[str, str]] = ()) -> bool:
    return bool(reviewer.people & author.people) or (reviewer.key, author.key) in extra


def eligible(problem: Problem, reviewer: Slot, submission: Slot) -> bool:
    pair = (reviewer.key, submission.key)
    return pair not in problem.existing and not conflicts(
        reviewer, submission, problem.extra_conflicts
    )


def balanced_assign(
    problem: Problem, reviewers: Sequence[Slot], submissions: Sequence[Slot]
) -> Allocation:
    """Give each submission `per_submission` distinct, non-conflicting reviewers, always
    choosing the reviewers with the fewest reviews so far (ties go to the earlier one in
    `reviewers`). Submissions with the fewest eligible reviewers are served first, so scarce
    reviewers are not used up early. If a submission has too few eligible reviewers it gets
    all it can and the gap is reported in `shortfall`."""
    load = {r.key: 0 for r in reviewers}
    position = {r.key: i for i, r in enumerate(reviewers)}
    options = {s.key: [r for r in reviewers if eligible(problem, r, s)] for s in submissions}
    order = sorted(submissions, key=lambda s: len(options[s.key]))  # stable
    pairs: list[tuple[str, str]] = []
    shortfall: dict[str, int] = {}
    for s in order:
        chosen = sorted(options[s.key], key=lambda r: (load[r.key], position[r.key]))
        chosen = chosen[: problem.per_submission]
        for r in chosen:
            load[r.key] += 1
            pairs.append((r.key, s.key))
        if len(chosen) < problem.per_submission:
            shortfall[s.key] = problem.per_submission - len(chosen)
    pairs = rebalance(problem, reviewers, pairs)
    index = {s.key: i for i, s in enumerate(submissions)}
    pairs.sort(key=lambda p: (index[p[1]], position[p[0]]))
    return Allocation(tuple(pairs), shortfall)


def rebalance(
    problem: Problem, reviewers: Sequence[Slot], pairs: list[tuple[str, str]]
) -> list[tuple[str, str]]:
    """Even out the load without changing who reviews each submission how many times.

    Greedy choice can leave one reviewer with more work than another even though a swap
    exists. Moving a review from reviewer A to B (B eligible, not already on it) may need a
    chain A -> B -> C where B hands one of its own reviews to C. This searches such chains
    from the busiest reviewers to any reviewer at least two reviews lighter, and applies them
    until no chain exists. The result is as even as the constraints allow."""
    by_key = {r.key: r for r in reviewers}
    subs = {s.key: s for s in problem.submissions}
    position = {r.key: i for i, r in enumerate(reviewers)}
    assigned: dict[str, set[str]] = {r.key: set() for r in reviewers}  # reviewer -> submissions
    reviewed_by: dict[str, set[str]] = {s.key: set() for s in problem.submissions}
    for rk, sk in pairs:
        assigned[rk].add(sk)
        reviewed_by[sk].add(rk)

    def can_take(rk: str, sk: str) -> bool:
        return rk not in reviewed_by[sk] and eligible(problem, by_key[rk], subs[sk])

    def find_chain(level: int) -> list[tuple[str, str, str]] | None:
        """A list of moves (from reviewer, submission, to reviewer) ending at a light reviewer."""
        sources = [r.key for r in reviewers if len(assigned[r.key]) == level]
        seen = set(sources)
        queue: list[tuple[str, list[tuple[str, str, str]]]] = [(k, []) for k in sources]
        for current, path in queue:
            for sk in sorted(assigned[current]):
                for r in reviewers:
                    rk = r.key
                    if rk in seen or not can_take(rk, sk):
                        continue
                    seen.add(rk)
                    step = [*path, (current, sk, rk)]
                    if len(assigned[rk]) <= level - 2:
                        return step
                    queue.append((rk, step))
        return None

    while True:
        counts = [len(a) for a in assigned.values()]
        if not counts or max(counts) - min(counts) <= 1:
            break
        for level in range(max(counts), min(counts) + 1, -1):
            chain = find_chain(level)
            if chain:
                for frm, sk, to in chain:
                    assigned[frm].discard(sk)
                    reviewed_by[sk].discard(frm)
                    assigned[to].add(sk)
                    reviewed_by[sk].add(to)
                break
        else:
            break
    result = [(rk, sk) for rk, subs_ in assigned.items() for sk in subs_]
    result.sort(key=lambda p: (position[p[0]], p[1]))
    return result


def loads(pairs: Iterable[tuple[str, str]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for reviewer, _ in pairs:
        counts[reviewer] = counts.get(reviewer, 0) + 1
    return counts
