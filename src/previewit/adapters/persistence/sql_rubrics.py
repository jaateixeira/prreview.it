"""SQL implementation of the rubric repository (SQLAlchemy Core; SQLite and PostgreSQL)."""

from __future__ import annotations

import json
from collections.abc import Sequence

from sqlalchemy import Engine, and_, delete, insert, select, update
from sqlalchemy.engine import Row

from previewit.adapters.persistence.tables import criteria, rubrics
from previewit.domain.identity import UserId
from previewit.domain.rubrics import Criterion, CriterionId, Rubric, RubricId
from previewit.domain.tenancy import OrgId, SpaceId


def _rubric(row: Row) -> Rubric:
    return Rubric(
        RubricId(row.id),
        OrgId(row.org_id),
        SpaceId(row.space_id),
        row.name,
        row.description,
        UserId(row.created_by),
    )


def _criterion(row: Row) -> Criterion:
    return Criterion(
        CriterionId(row.id),
        OrgId(row.org_id),
        RubricId(row.rubric_id),
        row.position,
        row.title,
        row.guidance,
        row.type_key,
        json.loads(row.config),
        row.weight,
        bool(row.required),
    )


def _criterion_values(c: Criterion) -> dict[str, object]:
    return {
        "id": c.id,
        "org_id": c.org_id,
        "rubric_id": c.rubric_id,
        "position": c.position,
        "title": c.title,
        "guidance": c.guidance,
        "type_key": c.type_key,
        "config": json.dumps(c.config, sort_keys=True),
        "weight": c.weight,
        "required": c.required,
    }


class SqlRubricRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def add_rubric(self, rubric: Rubric, items: Sequence[Criterion] = ()) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                insert(rubrics).values(
                    id=rubric.id,
                    org_id=rubric.org_id,
                    space_id=rubric.space_id,
                    name=rubric.name,
                    description=rubric.description,
                    created_by=rubric.created_by,
                )
            )
            for criterion in items:
                conn.execute(insert(criteria).values(**_criterion_values(criterion)))

    def get_rubric(self, rubric_id: RubricId) -> Rubric | None:
        with self._engine.connect() as conn:
            row = conn.execute(select(rubrics).where(rubrics.c.id == rubric_id)).first()
        return _rubric(row) if row else None

    def update_rubric(self, rubric: Rubric) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                update(rubrics)
                .where(and_(rubrics.c.id == rubric.id, rubrics.c.org_id == rubric.org_id))
                .values(name=rubric.name, description=rubric.description)
            )

    def delete_rubric(self, rubric_id: RubricId) -> None:
        with self._engine.begin() as conn:  # criteria go with it (ON DELETE CASCADE)
            conn.execute(delete(rubrics).where(rubrics.c.id == rubric_id))

    def rubrics_in_space(self, space_id: SpaceId) -> list[Rubric]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                select(rubrics).where(rubrics.c.space_id == space_id).order_by(rubrics.c.id)
            ).all()
        return sorted((_rubric(r) for r in rows), key=lambda r: (r.name.lower(), r.id))

    def add_criterion(self, criterion: Criterion) -> None:
        with self._engine.begin() as conn:
            conn.execute(insert(criteria).values(**_criterion_values(criterion)))

    def get_criterion(self, criterion_id: CriterionId) -> Criterion | None:
        with self._engine.connect() as conn:
            row = conn.execute(select(criteria).where(criteria.c.id == criterion_id)).first()
        return _criterion(row) if row else None

    def update_criterion(self, criterion: Criterion) -> None:
        values = _criterion_values(criterion)
        for fixed in ("id", "org_id", "rubric_id", "position"):
            del values[fixed]
        with self._engine.begin() as conn:
            conn.execute(
                update(criteria)
                .where(and_(criteria.c.id == criterion.id, criteria.c.org_id == criterion.org_id))
                .values(**values)
            )

    def delete_criterion(self, criterion_id: CriterionId) -> None:
        with self._engine.begin() as conn:
            conn.execute(delete(criteria).where(criteria.c.id == criterion_id))

    def criteria_of(self, rubric_id: RubricId) -> list[Criterion]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                select(criteria)
                .where(criteria.c.rubric_id == rubric_id)
                .order_by(criteria.c.position, criteria.c.id)
            ).all()
        return [_criterion(r) for r in rows]

    def set_positions(self, rubric_id: RubricId, order: Sequence[CriterionId]) -> None:
        with self._engine.begin() as conn:
            for position, cid in enumerate(order):
                conn.execute(
                    update(criteria)
                    .where(and_(criteria.c.id == cid, criteria.c.rubric_id == rubric_id))
                    .values(position=position)
                )
