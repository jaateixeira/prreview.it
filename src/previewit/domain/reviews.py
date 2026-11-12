"""A Review answers a rubric for one ReviewTask; Annotations pin comments to the content.

One task has at most one review. When the reviewer is a group, the review is shared: any
member may edit, a version number guards against overwriting someone else's save, and every
save is attributed in an append-only trail.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import NewType

from previewit.domain.identity import UserId
from previewit.domain.rounds import RoundId, TaskId
from previewit.domain.tenancy import OrgId, SpaceId

ReviewId = NewType("ReviewId", str)
AnnotationId = NewType("AnnotationId", str)

MAX_COMMENT_LENGTH = 2000


class InvalidReview(ValueError):
    pass


class ReviewConflict(Exception):
    """Someone saved this review after the version the editor started from."""


class ReviewClosed(Exception):
    """The round has closed; the review can no longer change."""


def clean_comment(value: str) -> str:
    text = value.replace("\r\n", "\n").strip()
    if not text or len(text) > MAX_COMMENT_LENGTH:
        raise InvalidReview(f"A comment must be 1-{MAX_COMMENT_LENGTH} characters.")
    return text


@dataclass(frozen=True)
class Review:
    id: ReviewId
    org_id: OrgId
    space_id: SpaceId
    round_id: RoundId
    task_id: TaskId
    answers: dict[str, str] = field(default_factory=dict[str, str])  # criterion id -> answer
    version: int = 1
    submitted: bool = False
    updated_by: UserId | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True)
class ReviewEdit:
    """One line of the trail: who saved which version, and when."""

    review_id: ReviewId
    version: int
    user_id: UserId
    at: datetime


@dataclass(frozen=True)
class Annotation:
    id: AnnotationId
    org_id: OrgId
    space_id: SpaceId
    review_id: ReviewId
    revision_number: int  # annotations are pinned to a revision, so they never drift
    kind: str  # the artifact type's annotation kind, e.g. "text"
    selector: dict[str, str]  # where, in the artifact type's own terms
    body: str
    created_by: UserId
    created_at: datetime
