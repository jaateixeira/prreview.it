"""SQL review repository (SQLAlchemy Core). Every row carries org_id."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy import Engine, Row, delete, insert, select, update
from sqlalchemy.exc import IntegrityError

from previewit.adapters.persistence.tables import annotations, review_edits, reviews
from previewit.application.ports import DuplicateReview
from previewit.domain.identity import UserId
from previewit.domain.reviews import Annotation, AnnotationId, Review, ReviewEdit, ReviewId
from previewit.domain.rounds import RoundId, TaskId
from previewit.domain.tenancy import OrgId, SpaceId


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def _review(row: Row) -> Review:
    return Review(
        ReviewId(row.id),
        OrgId(row.org_id),
        SpaceId(row.space_id),
        RoundId(row.round_id),
        TaskId(row.task_id),
        dict(json.loads(row.answers)),
        row.version,
        bool(row.submitted),
        UserId(row.updated_by) if row.updated_by else None,
        _utc(row.updated_at) if row.updated_at else None,
    )


def _annotation(row: Row) -> Annotation:
    return Annotation(
        AnnotationId(row.id),
        OrgId(row.org_id),
        SpaceId(row.space_id),
        ReviewId(row.review_id),
        row.revision_number,
        row.kind,
        dict(json.loads(row.selector)),
        row.body,
        UserId(row.created_by),
        _utc(row.created_at),
    )


def _edit_values(review: Review, edit: ReviewEdit) -> dict[str, object]:
    return {
        "review_id": edit.review_id,
        "version": edit.version,
        "org_id": review.org_id,
        "user_id": edit.user_id,
        "at": edit.at,
    }


class SqlReviewRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def get_review(self, review_id: ReviewId) -> Review | None:
        with self._engine.connect() as conn:
            row = conn.execute(select(reviews).where(reviews.c.id == review_id)).first()
        return _review(row) if row else None

    def review_of_task(self, task_id: TaskId) -> Review | None:
        with self._engine.connect() as conn:
            row = conn.execute(select(reviews).where(reviews.c.task_id == task_id)).first()
        return _review(row) if row else None

    def add_review(self, review: Review, edit: ReviewEdit) -> None:
        try:
            with self._engine.begin() as conn:
                conn.execute(
                    insert(reviews).values(
                        id=review.id,
                        org_id=review.org_id,
                        space_id=review.space_id,
                        round_id=review.round_id,
                        task_id=review.task_id,
                        answers=json.dumps(review.answers),
                        version=review.version,
                        submitted=review.submitted,
                        updated_by=review.updated_by,
                        updated_at=review.updated_at,
                    )
                )
                conn.execute(insert(review_edits).values(**_edit_values(review, edit)))
        except IntegrityError:
            raise DuplicateReview from None

    def update_review(self, review: Review, expected_version: int, edit: ReviewEdit) -> bool:
        with self._engine.begin() as conn:
            result = conn.execute(
                update(reviews)
                .where(reviews.c.id == review.id, reviews.c.version == expected_version)
                .values(
                    answers=json.dumps(review.answers),
                    version=review.version,
                    submitted=review.submitted,
                    updated_by=review.updated_by,
                    updated_at=review.updated_at,
                )
            )
            if result.rowcount != 1:
                return False  # someone saved first; nothing was written
            conn.execute(insert(review_edits).values(**_edit_values(review, edit)))
        return True

    def reviews_in_round(self, round_id: RoundId) -> list[Review]:
        with self._engine.connect() as conn:
            rows = conn.execute(select(reviews).where(reviews.c.round_id == round_id)).all()
        return [_review(r) for r in rows]

    def edits_of(self, review_id: ReviewId) -> list[ReviewEdit]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                select(review_edits)
                .where(review_edits.c.review_id == review_id)
                .order_by(review_edits.c.version)
            ).all()
        return [
            ReviewEdit(ReviewId(r.review_id), r.version, UserId(r.user_id), _utc(r.at))
            for r in rows
        ]

    def add_annotation(self, annotation: Annotation) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                insert(annotations).values(
                    id=annotation.id,
                    org_id=annotation.org_id,
                    space_id=annotation.space_id,
                    review_id=annotation.review_id,
                    revision_number=annotation.revision_number,
                    kind=annotation.kind,
                    selector=json.dumps(annotation.selector),
                    body=annotation.body,
                    created_by=annotation.created_by,
                    created_at=annotation.created_at,
                )
            )

    def get_annotation(self, annotation_id: AnnotationId) -> Annotation | None:
        with self._engine.connect() as conn:
            row = conn.execute(select(annotations).where(annotations.c.id == annotation_id)).first()
        return _annotation(row) if row else None

    def delete_annotation(self, annotation_id: AnnotationId) -> None:
        with self._engine.begin() as conn:
            conn.execute(delete(annotations).where(annotations.c.id == annotation_id))

    def annotations_of(self, review_id: ReviewId) -> list[Annotation]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                select(annotations)
                .where(annotations.c.review_id == review_id)
                .order_by(annotations.c.created_at, annotations.c.id)
            ).all()
        return [_annotation(r) for r in rows]
