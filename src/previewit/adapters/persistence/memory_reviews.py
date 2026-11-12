"""In-memory review repository: a fast fake that follows the same contract as the SQL one."""

from __future__ import annotations

from previewit.application.ports import DuplicateReview
from previewit.domain.reviews import Annotation, AnnotationId, Review, ReviewEdit, ReviewId
from previewit.domain.rounds import RoundId, TaskId


class InMemoryReviewRepository:
    def __init__(self) -> None:
        self._reviews: dict[ReviewId, Review] = {}
        self._edits: dict[ReviewId, list[ReviewEdit]] = {}
        self._annotations: dict[AnnotationId, Annotation] = {}

    def get_review(self, review_id: ReviewId) -> Review | None:
        return self._reviews.get(review_id)

    def review_of_task(self, task_id: TaskId) -> Review | None:
        return next((r for r in self._reviews.values() if r.task_id == task_id), None)

    def add_review(self, review: Review, edit: ReviewEdit) -> None:
        if self.review_of_task(review.task_id) is not None:
            raise DuplicateReview
        self._reviews[review.id] = review
        self._edits[review.id] = [edit]

    def update_review(self, review: Review, expected_version: int, edit: ReviewEdit) -> bool:
        current = self._reviews.get(review.id)
        if current is None or current.version != expected_version:
            return False
        self._reviews[review.id] = review
        self._edits[review.id].append(edit)
        return True

    def reviews_in_round(self, round_id: RoundId) -> list[Review]:
        return [r for r in self._reviews.values() if r.round_id == round_id]

    def edits_of(self, review_id: ReviewId) -> list[ReviewEdit]:
        return list(self._edits.get(review_id, []))

    def add_annotation(self, annotation: Annotation) -> None:
        self._annotations[annotation.id] = annotation

    def get_annotation(self, annotation_id: AnnotationId) -> Annotation | None:
        return self._annotations.get(annotation_id)

    def delete_annotation(self, annotation_id: AnnotationId) -> None:
        self._annotations.pop(annotation_id, None)

    def annotations_of(self, review_id: ReviewId) -> list[Annotation]:
        found = [a for a in self._annotations.values() if a.review_id == review_id]
        return sorted(found, key=lambda a: (a.created_at, a.id))
