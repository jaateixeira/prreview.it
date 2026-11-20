"""AI reviews kept in memory, for tests (ADR 0025)."""

from __future__ import annotations

from datetime import datetime

from previewit.domain.ai_reviews import AiReview, AiReviewId, Payer
from previewit.domain.calls import SubmissionId
from previewit.domain.identity import UserId


class InMemoryAiReviewRepository:
    def __init__(self) -> None:
        self._rows: dict[AiReviewId, AiReview] = {}

    def add(self, review: AiReview) -> None:
        self._rows[review.id] = review

    def save(self, review: AiReview) -> None:
        self._rows[review.id] = review

    def get(self, review_id: AiReviewId) -> AiReview | None:
        return self._rows.get(review_id)

    def for_submission(self, submission_id: SubmissionId) -> list[AiReview]:
        found = [r for r in self._rows.values() if r.submission_id == submission_id]
        return sorted(found, key=lambda r: (r.requested_at, r.id))

    def unfinished(self) -> list[AiReview]:
        return sorted(
            (r for r in self._rows.values() if not r.finished), key=lambda r: r.requested_at
        )

    def free_since(self, user_id: UserId, since: datetime) -> int:
        return sum(
            1
            for r in self._rows.values()
            if r.requested_by == user_id and r.payer is Payer.FREE and r.requested_at >= since
        )
