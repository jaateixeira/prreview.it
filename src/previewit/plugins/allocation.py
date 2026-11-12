"""Built-in allocation strategies: random, round robin, manual."""

from __future__ import annotations

import random

from previewit.domain.allocation import Allocation, Problem, balanced_assign


class RandomStrategy:
    key = "random"
    label = "Random"
    automatic = True

    def allocate(self, problem: Problem, seed: int) -> Allocation:
        rng = random.Random(seed)
        reviewers, submissions = list(problem.reviewers), list(problem.submissions)
        rng.shuffle(reviewers)
        rng.shuffle(submissions)
        return balanced_assign(problem, reviewers, submissions)


class RoundRobinStrategy:
    key = "round_robin"
    label = "Round robin"
    automatic = True

    def allocate(self, problem: Problem, seed: int) -> Allocation:
        """Deterministic: the reviewer list is rotated for each submission, so neighbours
        review each other in a fixed pattern. `seed` shifts where the rotation starts."""
        reviewers, submissions = list(problem.reviewers), list(problem.submissions)
        n = len(reviewers)
        if n:
            shift = seed % n
            reviewers = reviewers[shift:] + reviewers[:shift]
        return balanced_assign(problem, reviewers, submissions)


class ManualStrategy:
    key = "manual"
    label = "Manual"
    automatic = False

    def allocate(self, problem: Problem, seed: int) -> Allocation:
        return Allocation((), {s.key: problem.per_submission for s in problem.submissions})
