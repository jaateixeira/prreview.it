"""In-memory rubric repository: a fast fake that follows the same contract as the SQL one."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from typing import Any

from previewit.domain.rubrics import Criterion, CriterionId, Rubric, RubricId, ordered
from previewit.domain.tenancy import SpaceId


class InMemoryRubricRepository:
    def __init__(self) -> None:
        self._rubrics: dict[RubricId, Rubric] = {}
        self._criteria: dict[CriterionId, Criterion] = {}

    def add_rubric(self, rubric: Rubric, items: Sequence[Criterion] = ()) -> None:
        self._rubrics[rubric.id] = rubric
        for criterion in items:
            self._criteria[criterion.id] = _copy(criterion)

    def get_rubric(self, rubric_id: RubricId) -> Rubric | None:
        return self._rubrics.get(rubric_id)

    def update_rubric(self, rubric: Rubric) -> None:
        if rubric.id in self._rubrics:
            self._rubrics[rubric.id] = rubric

    def delete_rubric(self, rubric_id: RubricId) -> None:
        self._rubrics.pop(rubric_id, None)
        for cid in [c.id for c in self._criteria.values() if c.rubric_id == rubric_id]:
            del self._criteria[cid]

    def rubrics_in_space(self, space_id: SpaceId) -> list[Rubric]:
        found = [r for r in self._rubrics.values() if r.space_id == space_id]
        return sorted(found, key=lambda r: (r.name.lower(), r.id))

    def add_criterion(self, criterion: Criterion) -> None:
        self._criteria[criterion.id] = _copy(criterion)

    def get_criterion(self, criterion_id: CriterionId) -> Criterion | None:
        found = self._criteria.get(criterion_id)
        return _copy(found) if found else None

    def update_criterion(self, criterion: Criterion) -> None:
        if criterion.id in self._criteria:
            self._criteria[criterion.id] = _copy(criterion)

    def delete_criterion(self, criterion_id: CriterionId) -> None:
        self._criteria.pop(criterion_id, None)

    def criteria_of(self, rubric_id: RubricId) -> list[Criterion]:
        return [
            _copy(c)
            for c in ordered([c for c in self._criteria.values() if c.rubric_id == rubric_id])
        ]

    def set_positions(self, rubric_id: RubricId, order: Sequence[CriterionId]) -> None:
        for position, cid in enumerate(order):
            criterion = self._criteria.get(cid)
            if criterion is not None and criterion.rubric_id == rubric_id:
                self._criteria[cid] = replace(criterion, position=position)


def _copy(criterion: Criterion) -> Criterion:
    config: dict[str, Any] = dict(criterion.config)
    return replace(criterion, config=config)
