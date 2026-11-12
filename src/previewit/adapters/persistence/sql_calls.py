"""SQL implementation of the call repository (SQLAlchemy Core; SQLite and PostgreSQL)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import Engine, and_, delete, func, insert, or_, select, update
from sqlalchemy.engine import Row
from sqlalchemy.exc import IntegrityError

from previewit.adapters.persistence.tables import (
    calls,
    revisions,
    share_grants,
    share_links,
    submissions,
)
from previewit.application.ports import DuplicateSubmission
from previewit.domain.calls import (
    Artifact,
    Call,
    CallAccess,
    CallId,
    Revision,
    RevisionInfo,
    ShareGrant,
    ShareLink,
    ShareTarget,
    Submission,
    SubmissionId,
)
from previewit.domain.identity import UserId
from previewit.domain.party import GroupParty, Party, UserParty
from previewit.domain.rubrics import RubricId
from previewit.domain.tenancy import OrgId, SpaceId


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def _opt_utc(value: datetime | None) -> datetime | None:
    return None if value is None else _utc(value)


def _party_columns(party: Party) -> tuple[str, str]:
    if isinstance(party, UserParty):
        return "user", party.user_id
    return "group", party.group_id


def _party(kind: str, ident: str) -> Party:
    return UserParty(ident) if kind == "user" else GroupParty(ident)


def _call(row: Row) -> Call:
    return Call(
        CallId(row.id),
        OrgId(row.org_id),
        SpaceId(row.space_id),
        row.title,
        row.description,
        row.artifact_type,
        bool(row.group_work),
        _opt_utc(row.closes_at),
        bool(row.published),
        UserId(row.created_by),
        RubricId(row.rubric_id) if row.rubric_id else None,
        CallAccess(row.access),
    )


def _submission(row: Row) -> Submission:
    return Submission(
        SubmissionId(row.id),
        OrgId(row.org_id),
        SpaceId(row.space_id),
        CallId(row.call_id),
        _party(row.author_kind, row.author_id),
        row.title,
        _utc(row.created_at),
    )


def _link(row: Row) -> ShareLink:
    return ShareLink(
        row.id,
        OrgId(row.org_id),
        SpaceId(row.space_id),
        ShareTarget(row.target),
        row.target_id,
        UserId(row.created_by),
        _utc(row.expires_at),
        bool(row.revoked),
    )


class SqlCallRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    # -- calls ------------------------------------------------------------------------

    def add_call(self, call: Call) -> None:
        with self._engine.begin() as conn:
            conn.execute(insert(calls).values(**_call_values(call)))

    def get_call(self, call_id: CallId) -> Call | None:
        with self._engine.connect() as conn:
            row = conn.execute(select(calls).where(calls.c.id == call_id)).first()
        return _call(row) if row else None

    def update_call(self, call: Call) -> None:
        values = _call_values(call)
        del values["id"], values["org_id"], values["space_id"], values["created_by"]
        with self._engine.begin() as conn:
            conn.execute(
                update(calls)
                .where(and_(calls.c.id == call.id, calls.c.org_id == call.org_id))
                .values(**values)
            )

    def delete_call(self, call_id: CallId) -> None:
        with self._engine.begin() as conn:
            subs = select(submissions.c.id).where(submissions.c.call_id == call_id)
            conn.execute(delete(share_links).where(_target(ShareTarget.CALL, call_id)))
            conn.execute(delete(share_grants).where(_grant_target(ShareTarget.CALL, call_id)))
            for target_id in conn.execute(subs).scalars().all():
                conn.execute(delete(share_links).where(_target(ShareTarget.SUBMISSION, target_id)))
                conn.execute(
                    delete(share_grants).where(_grant_target(ShareTarget.SUBMISSION, target_id))
                )
            # Revisions and submissions go with the call through ON DELETE CASCADE.
            conn.execute(delete(calls).where(calls.c.id == call_id))

    def calls_in_space(self, space_id: SpaceId) -> list[Call]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                select(calls)
                .where(calls.c.space_id == space_id)
                .order_by(calls.c.created_at, calls.c.id)
            ).all()
        return [_call(r) for r in rows]

    def calls_using_rubric(self, rubric_id: RubricId) -> list[Call]:
        with self._engine.connect() as conn:
            rows = conn.execute(select(calls).where(calls.c.rubric_id == rubric_id)).all()
        return [_call(r) for r in rows]

    # -- submissions and revisions ------------------------------------------------------

    def add_submission(
        self, submission: Submission, artifact: Artifact, created_by: UserId, now: datetime
    ) -> Revision:
        kind, ident = _party_columns(submission.author)
        try:
            with self._engine.begin() as conn:
                conn.execute(
                    insert(submissions).values(
                        id=submission.id,
                        org_id=submission.org_id,
                        space_id=submission.space_id,
                        call_id=submission.call_id,
                        author_kind=kind,
                        author_id=ident,
                        title=submission.title,
                        created_at=submission.created_at,
                    )
                )
                conn.execute(
                    insert(revisions).values(
                        **_revision_values(
                            submission.id, submission.org_id, 1, artifact, created_by, now
                        )
                    )
                )
        except IntegrityError:
            if self.get_submission_for_party(submission.call_id, submission.author) is not None:
                raise DuplicateSubmission from None
            raise
        return Revision(submission.id, submission.org_id, 1, artifact, created_by, now)

    def get_submission_for_party(self, call_id: CallId, party: Party) -> Submission | None:
        kind, ident = _party_columns(party)
        with self._engine.connect() as conn:
            row = conn.execute(
                select(submissions).where(
                    submissions.c.call_id == call_id,
                    submissions.c.author_kind == kind,
                    submissions.c.author_id == ident,
                )
            ).first()
        return _submission(row) if row else None

    def get_submission(self, submission_id: SubmissionId) -> Submission | None:
        with self._engine.connect() as conn:
            row = conn.execute(select(submissions).where(submissions.c.id == submission_id)).first()
        return _submission(row) if row else None

    def submissions_in_call(self, call_id: CallId) -> list[Submission]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                select(submissions)
                .where(submissions.c.call_id == call_id)
                .order_by(submissions.c.created_at, submissions.c.id)
            ).all()
        return [_submission(r) for r in rows]

    def submissions_of_parties(self, call_id: CallId, parties: Sequence[Party]) -> list[Submission]:
        if not parties:
            return []
        match = or_(
            *(
                and_(
                    submissions.c.author_kind == _party_columns(p)[0],
                    submissions.c.author_id == _party_columns(p)[1],
                )
                for p in parties
            )
        )
        with self._engine.connect() as conn:
            rows = conn.execute(
                select(submissions)
                .where(submissions.c.call_id == call_id, match)
                .order_by(submissions.c.created_at, submissions.c.id)
            ).all()
        return [_submission(r) for r in rows]

    def add_revision(
        self, submission_id: SubmissionId, artifact: Artifact, created_by: UserId, now: datetime
    ) -> Revision:
        for attempt in range(5):
            try:
                with self._engine.begin() as conn:
                    org_id = conn.execute(
                        select(submissions.c.org_id).where(submissions.c.id == submission_id)
                    ).scalar_one()
                    last = conn.execute(
                        select(func.max(revisions.c.number)).where(
                            revisions.c.submission_id == submission_id
                        )
                    ).scalar()
                    number = (last or 0) + 1
                    conn.execute(
                        insert(revisions).values(
                            **_revision_values(
                                submission_id, org_id, number, artifact, created_by, now
                            )
                        )
                    )
                return Revision(submission_id, OrgId(org_id), number, artifact, created_by, now)
            except IntegrityError:  # two people saved at once: take the next free number
                if attempt == 4:
                    raise
        raise AssertionError("unreachable")

    def revision_infos(self, submission_id: SubmissionId) -> list[RevisionInfo]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                select(
                    revisions.c.number,
                    revisions.c.media_type,
                    revisions.c.size,
                    revisions.c.digest,
                    revisions.c.filename,
                    revisions.c.created_by,
                    revisions.c.created_at,
                )
                .where(revisions.c.submission_id == submission_id)
                .order_by(revisions.c.number)
            ).all()
        return [
            RevisionInfo(
                r.number,
                r.media_type,
                r.size,
                r.digest,
                r.filename,
                UserId(r.created_by),
                _utc(r.created_at),
            )
            for r in rows
        ]

    def get_revision(self, submission_id: SubmissionId, number: int) -> Revision | None:
        with self._engine.connect() as conn:
            row = conn.execute(
                select(revisions).where(
                    revisions.c.submission_id == submission_id, revisions.c.number == number
                )
            ).first()
        if row is None:
            return None
        artifact = Artifact(row.type_key, row.media_type, bytes(row.content), row.filename)
        return Revision(
            SubmissionId(row.submission_id),
            OrgId(row.org_id),
            row.number,
            artifact,
            UserId(row.created_by),
            _utc(row.created_at),
        )

    # -- sharing ----------------------------------------------------------------------------

    def add_share_link(self, link: ShareLink) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                insert(share_links).values(
                    id=link.id,
                    org_id=link.org_id,
                    space_id=link.space_id,
                    target=link.target.value,
                    target_id=link.target_id,
                    created_by=link.created_by,
                    expires_at=link.expires_at,
                    revoked=link.revoked,
                )
            )

    def get_share_link(self, link_id: str) -> ShareLink | None:
        with self._engine.connect() as conn:
            row = conn.execute(select(share_links).where(share_links.c.id == link_id)).first()
        return _link(row) if row else None

    def share_links_for(self, target: ShareTarget, target_id: str) -> list[ShareLink]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                select(share_links)
                .where(_target(target, target_id))
                .order_by(share_links.c.expires_at)
            ).all()
        return [_link(r) for r in rows]

    def revoke_share_link(self, link_id: str) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                update(share_links).where(share_links.c.id == link_id).values(revoked=True)
            )

    def count_share_links(self, created_by: UserId) -> int:
        with self._engine.connect() as conn:
            return int(
                conn.execute(
                    select(func.count())
                    .select_from(share_links)
                    .where(share_links.c.created_by == created_by)
                ).scalar_one()
            )

    def add_share_grant(self, grant: ShareGrant) -> None:
        try:
            with self._engine.begin() as conn:
                conn.execute(
                    insert(share_grants).values(
                        user_id=grant.user_id,
                        target=grant.target.value,
                        target_id=grant.target_id,
                        org_id=grant.org_id,
                        space_id=grant.space_id,
                    )
                )
        except IntegrityError:
            if not self.has_share_grant(grant.user_id, grant.target, grant.target_id):
                raise

    def has_share_grant(self, user_id: UserId, target: ShareTarget, target_id: str) -> bool:
        with self._engine.connect() as conn:
            return (
                conn.execute(
                    select(share_grants.c.user_id).where(
                        share_grants.c.user_id == user_id, _grant_target(target, target_id)
                    )
                ).first()
                is not None
            )

    def share_grants_for(self, user_id: UserId) -> list[ShareGrant]:
        with self._engine.connect() as conn:
            rows = conn.execute(select(share_grants).where(share_grants.c.user_id == user_id)).all()
        return [
            ShareGrant(
                OrgId(r.org_id),
                SpaceId(r.space_id),
                UserId(r.user_id),
                ShareTarget(r.target),
                r.target_id,
            )
            for r in rows
        ]


def _target(target: ShareTarget, target_id: str):
    return and_(share_links.c.target == target.value, share_links.c.target_id == target_id)


def _grant_target(target: ShareTarget, target_id: str):
    return and_(share_grants.c.target == target.value, share_grants.c.target_id == target_id)


def _call_values(call: Call) -> dict[str, object]:
    return {
        "id": call.id,
        "org_id": call.org_id,
        "space_id": call.space_id,
        "title": call.title,
        "description": call.description,
        "artifact_type": call.artifact_type,
        "group_work": call.group_work,
        "closes_at": call.closes_at,
        "published": call.published,
        "created_by": call.created_by,
        "rubric_id": call.rubric_id,
        "access": call.access.value,
    }


def _revision_values(
    submission_id: str, org_id: str, number: int, artifact: Artifact, by: UserId, now: datetime
) -> dict[str, object]:
    return {
        "submission_id": submission_id,
        "number": number,
        "org_id": org_id,
        "type_key": artifact.type_key,
        "media_type": artifact.media_type,
        "filename": artifact.filename,
        "size": artifact.size,
        "digest": artifact.digest,
        "content": artifact.content,
        "created_by": by,
        "created_at": now,
    }
