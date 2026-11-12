"""SQL round repository (SQLAlchemy Core). Every row carries org_id."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import Connection, Engine, Row, and_, delete, func, insert, or_, select, update
from sqlalchemy.exc import IntegrityError

from previewit.adapters.persistence.tables import (
    invitation_submissions,
    invitations,
    review_rounds,
    review_tasks,
)
from previewit.application.ports import DuplicateRound, DuplicateTask
from previewit.domain.calls import CallId, SubmissionId
from previewit.domain.identity import Email, UserId
from previewit.domain.invitations import Invitation
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
            ids = select(invitations.c.id).where(invitations.c.round_id == round_id)
            conn.execute(
                delete(invitation_submissions).where(
                    invitation_submissions.c.invitation_id.in_(ids)
                )
            )
            conn.execute(delete(invitations).where(invitations.c.round_id == round_id))
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

    # -- reviewer invitations ------------------------------------------------------------------

    def add_invitation(self, invitation: Invitation) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                insert(invitations).values(
                    id=invitation.id,
                    org_id=invitation.org_id,
                    space_id=invitation.space_id,
                    round_id=invitation.round_id,
                    email=invitation.email.value,
                    created_by=invitation.created_by,
                    expires_at=invitation.expires_at,
                    revoked=invitation.revoked,
                    accepted_by=invitation.accepted_by,
                )
            )
            if invitation.submission_ids:
                conn.execute(
                    insert(invitation_submissions),
                    [
                        {
                            "invitation_id": invitation.id,
                            "submission_id": submission_id,
                            "org_id": invitation.org_id,
                            "position": position,
                        }
                        for position, submission_id in enumerate(invitation.submission_ids)
                    ],
                )

    def get_invitation(self, invitation_id: str) -> Invitation | None:
        with self._engine.connect() as conn:
            row = conn.execute(select(invitations).where(invitations.c.id == invitation_id)).first()
            return _invitation(conn, row) if row else None

    def update_invitation(self, invitation: Invitation) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                update(invitations)
                .where(invitations.c.id == invitation.id)
                .values(revoked=invitation.revoked, accepted_by=invitation.accepted_by)
            )

    def invitations_of_round(self, round_id: RoundId) -> list[Invitation]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                select(invitations)
                .where(invitations.c.round_id == round_id)
                .order_by(invitations.c.expires_at, invitations.c.id)
            ).all()
            return [_invitation(conn, r) for r in rows]

    def count_invitations(self, created_by: UserId) -> int:
        with self._engine.connect() as conn:
            return int(
                conn.execute(
                    select(func.count())
                    .select_from(invitations)
                    .where(invitations.c.created_by == created_by)
                ).scalar_one()
            )


def _invitation(conn: Connection, row: Row) -> Invitation:
    work = conn.execute(
        select(invitation_submissions.c.submission_id)
        .where(invitation_submissions.c.invitation_id == row.id)
        .order_by(invitation_submissions.c.position)
    ).scalars()
    return Invitation(
        row.id,
        OrgId(row.org_id),
        SpaceId(row.space_id),
        RoundId(row.round_id),
        Email(row.email),
        tuple(SubmissionId(s) for s in work),
        UserId(row.created_by),
        _utc(row.expires_at),  # type: ignore[arg-type]
        bool(row.revoked),
        UserId(row.accepted_by) if row.accepted_by else None,
    )
