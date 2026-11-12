"""SQL round repository (SQLAlchemy Core). Every row carries org_id."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import Connection, Engine, Row, and_, delete, insert, or_, select, update
from sqlalchemy.exc import IntegrityError

from previewit.adapters.persistence.tables import review_rounds, review_tasks
from previewit.application.ports import DuplicateRound, DuplicateTask
from previewit.domain.calls import CallId, SubmissionId
from previewit.domain.party import GroupParty, Party, UserParty
from previewit.domain.rounds import ReviewRound, ReviewTask, RoundId, TaskId
from previewit.domain.tenancy import OrgId, SpaceId


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def _party_columns(party: Party) -> tuple[str, str]:
    if isinstance(party, UserParty):
        return "user", party.user_id
    return "group", party.group_id


def _round(row: Row) -> ReviewRound:
    return ReviewRound(
        RoundId(row.id),
        OrgId(row.org_id),
        SpaceId(row.space_id),
        CallId(row.call_id),
        row.number,
        row.per_submission,
        row.strategy_key,
        row.anonymity_key,
        _utc(row.opens_at),
        _utc(row.closes_at),
    )


def _task(row: Row) -> ReviewTask:
    reviewer: Party = (
        UserParty(row.reviewer_id) if row.reviewer_kind == "user" else GroupParty(row.reviewer_id)
    )
    return ReviewTask(
        TaskId(row.id),
        OrgId(row.org_id),
        SpaceId(row.space_id),
        RoundId(row.round_id),
        reviewer,
        SubmissionId(row.submission_id),
        row.revision_number,
        bool(row.manual),
    )


def _task_values(task: ReviewTask) -> dict[str, object]:
    kind, ident = _party_columns(task.reviewer)
    return {
        "id": task.id,
        "org_id": task.org_id,
        "space_id": task.space_id,
        "round_id": task.round_id,
        "reviewer_kind": kind,
        "reviewer_id": ident,
        "submission_id": task.submission_id,
        "revision_number": task.revision_number,
        "manual": task.manual,
    }


def _insert_tasks(conn: Connection, tasks: Sequence[ReviewTask]) -> None:
    if tasks:
        conn.execute(insert(review_tasks), [_task_values(t) for t in tasks])


class SqlRoundRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def add_round(self, round_: ReviewRound) -> None:
        try:
            with self._engine.begin() as conn:
                conn.execute(
                    insert(review_rounds).values(
                        id=round_.id,
                        org_id=round_.org_id,
                        space_id=round_.space_id,
                        call_id=round_.call_id,
                        number=round_.number,
                        per_submission=round_.per_submission,
                        strategy_key=round_.strategy_key,
                        anonymity_key=round_.anonymity_key,
                        opens_at=round_.opens_at,
                        closes_at=round_.closes_at,
                    )
                )
        except IntegrityError:
            raise DuplicateRound from None

    def get_round(self, round_id: RoundId) -> ReviewRound | None:
        with self._engine.connect() as conn:
            row = conn.execute(select(review_rounds).where(review_rounds.c.id == round_id)).first()
        return _round(row) if row else None

    def update_round(self, round_: ReviewRound) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                update(review_rounds)
                .where(review_rounds.c.id == round_.id)
                .values(
                    per_submission=round_.per_submission,
                    strategy_key=round_.strategy_key,
                    anonymity_key=round_.anonymity_key,
                    opens_at=round_.opens_at,
                    closes_at=round_.closes_at,
                )
            )

    def delete_round(self, round_id: RoundId) -> None:
        with self._engine.begin() as conn:
            conn.execute(delete(review_tasks).where(review_tasks.c.round_id == round_id))
            conn.execute(delete(review_rounds).where(review_rounds.c.id == round_id))

    def rounds_of_call(self, call_id: CallId) -> list[ReviewRound]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                select(review_rounds)
                .where(review_rounds.c.call_id == call_id)
                .order_by(review_rounds.c.number)
            ).all()
        return [_round(r) for r in rows]

    def add_tasks(self, tasks: Sequence[ReviewTask]) -> None:
        try:
            with self._engine.begin() as conn:
                _insert_tasks(conn, tasks)
        except IntegrityError:
            raise DuplicateTask from None

    def replace_tasks(self, round_id: RoundId, tasks: Sequence[ReviewTask]) -> None:
        with self._engine.begin() as conn:
            conn.execute(delete(review_tasks).where(review_tasks.c.round_id == round_id))
            _insert_tasks(conn, tasks)

    def get_task(self, task_id: TaskId) -> ReviewTask | None:
        with self._engine.connect() as conn:
            row = conn.execute(select(review_tasks).where(review_tasks.c.id == task_id)).first()
        return _task(row) if row else None

    def delete_task(self, task_id: TaskId) -> None:
        with self._engine.begin() as conn:
            conn.execute(delete(review_tasks).where(review_tasks.c.id == task_id))

    def tasks_of_round(self, round_id: RoundId) -> list[ReviewTask]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                select(review_tasks).where(review_tasks.c.round_id == round_id)
            ).all()
        return [_task(r) for r in rows]

    def tasks_for_parties(self, space_id: SpaceId, parties: Sequence[Party]) -> list[ReviewTask]:
        if not parties:
            return []
        match = or_(
            *(
                and_(
                    review_tasks.c.reviewer_kind == kind,
                    review_tasks.c.reviewer_id == ident,
                )
                for kind, ident in map(_party_columns, parties)
            )
        )
        with self._engine.connect() as conn:
            rows = conn.execute(
                select(review_tasks).where(review_tasks.c.space_id == space_id, match)
            ).all()
        return [_task(r) for r in rows]
