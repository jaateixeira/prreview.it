# Writing an allocation strategy

A strategy decides which reviewer Party reviews which submission. The built-ins are `random`, `round_robin` and `manual` (`src/previewit/plugins/allocation.py`). The API is not stable before v0.2.

```python
class AllocationStrategy(Protocol):
    key: str  # stored on every round, e.g. "random"
    label: str  # shown when a round is configured
    automatic: bool  # False: the organizer pairs people by hand

    def allocate(self, problem: Problem, seed: int) -> Allocation: ...
```

- `Problem` (`previewit.domain.allocation`) lists `reviewers` and `submissions` as `Slot(key, people)`: the people behind each Party (one person, or a group's members). `per_submission` is how many reviews each submission should get; `extra_conflicts` and `existing` are pairs to avoid.
- Return `Allocation(pairs, shortfall)`: `(reviewer key, submission key)` pairs, and for each submission the number of reviewers it is missing.
- A pair is a conflict when the two sides share a person (this covers yourself, your own group and your group's members). `conflicts(reviewer, author, extra)` and `eligible(problem, reviewer, submission)` implement the rule; use them.
- `balanced_assign(problem, reviewers, submissions)` gives each submission its reviewers while keeping everybody's load as even as the constraints allow. A strategy that only wants a different order or tie-break can reorder the lists and call it, as the built-ins do.
- `allocate` must be a pure function of `problem` and `seed`: the same input gives the same output, with no clock, I/O or global random state.
- Register it in `pyproject.toml` under `[project.entry-points."previewit.plugins"]`, for example `mine = "my_package.module:MyStrategy"`. Restart after installing.
- Plugins may import `previewit.application` and `previewit.domain`, never `previewit.adapters` (checked by `make layers`).
- Property-test your strategy like the built-ins: no conflicts, no repeats, exactly `per_submission` reviewers whenever enough eligible reviewers exist, and the shortfall reported otherwise (`tests/unit/test_allocation.py`).
