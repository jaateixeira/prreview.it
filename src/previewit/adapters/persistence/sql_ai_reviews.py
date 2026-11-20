"""AI reviews in the database (ADR 0025). No column holds a key."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import ROUND_CEILING, Decimal
from typing import Any

from sqlalchemy import Engine, func, insert, select, update

from previewit.adapters.persistence.tables import ai_reviews
from previewit.domain.ai_reviews import AiReview, AiReviewId, AiReviewStatus, Payer
from previewit.domain.calls import SubmissionId
from previewit.domain.identity import UserId
from previewit.domain.tenancy import OrgId

MICRO = Decimal(1_000_000)
UNFINISHED = (AiReviewStatus.WAITING.value, AiReviewStatus.WRITING.value)


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value  # SQLite drops the zone


def _row(review: AiReview) -> dict[str, Any]:
    return {
        "id": review.id,
        "org_id": review.org_id,
        "submission_id": review.submission_id,
        "revision": review.revision,
        "model_key": review.model_key,
        "model_name": review.model_name,
        "hosted_in": review.hosted_in,
        "hosting": review.hosting,
        "payer": review.payer.value,
        "requested_by": review.requested_by,
        "requested_at": review.requested_at,
        "note": review.note,
        "status": review.status.value,
        "finished_at": review.finished_at,
        "text": review.text,
        "problem": review.problem,
        "input_tokens": review.input_tokens,
        "output_tokens": review.output_tokens,
        "cost_microusd": int((review.cost_usd * MICRO).to_integral_value(ROUND_CEILING)),
    }


def _review(row: Any) -> AiReview:
    requested_at = _utc(row.requested_at)
    assert requested_at is not None
    return AiReview(
        id=AiReviewId(row.id),
        org_id=OrgId(row.org_id),
        submission_id=SubmissionId(row.submission_id),
        revision=row.revision,
        model_key=row.model_key,
        model_name=row.model_name,
        hosted_in=row.hosted_in,
        hosting=row.hosting,
        payer=Payer(row.payer),
        requested_by=UserId(row.requested_by),
        requested_at=requested_at,
        note=row.note,
        status=AiReviewStatus(row.status),
        finished_at=_utc(row.finished_at),
        text=row.text,
        problem=row.problem,
        input_tokens=row.input_tokens,
        output_tokens=row.output_tokens,
        cost_usd=Decimal(row.cost_microusd) / MICRO,
    )


class SqlAiReviewRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def add(self, review: AiReview) -> None:
        with self._engine.begin() as conn:
            conn.execute(insert(ai_reviews).values(**_row(review)))

    def save(self, review: AiReview) -> None:
        values = _row(review)
        del values["id"]
        with self._engine.begin() as conn:
            conn.execute(update(ai_reviews).where(ai_reviews.c.id == review.id).values(**values))

    def get(self, review_id: AiReviewId) -> AiReview | None:
        with self._engine.connect() as conn:
            row = conn.execute(select(ai_reviews).where(ai_reviews.c.id == review_id)).one_or_none()
        return _review(row) if row is not None else None

    def for_submission(self, submission_id: SubmissionId) -> list[AiReview]:
        query = (
            select(ai_reviews)
            .where(ai_reviews.c.submission_id == submission_id)
            .order_by(ai_reviews.c.requested_at, ai_reviews.c.id)
        )
        with self._engine.connect() as conn:
            return [_review(row) for row in conn.execute(query)]

    def unfinished(self) -> list[AiReview]:
        query = (
            select(ai_reviews)
            .where(ai_reviews.c.status.in_(UNFINISHED))
            .order_by(ai_reviews.c.requested_at)
        )
        with self._engine.connect() as conn:
            return [_review(row) for row in conn.execute(query)]

    def free_since(self, user_id: UserId, since: datetime) -> int:
        query = (
            select(func.count())
            .select_from(ai_reviews)
            .where(
                ai_reviews.c.requested_by == user_id,
                ai_reviews.c.payer == Payer.FREE.value,
                ai_reviews.c.requested_at >= since,
            )
        )
        with self._engine.connect() as conn:
            return conn.execute(query).scalar_one()
