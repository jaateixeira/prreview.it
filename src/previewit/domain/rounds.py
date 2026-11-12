"""Review rounds and the tasks that allocation produces.

A Call can have any number of rounds, numbered 1, 2, 3, ... Each round has its own
cardinality, allocation strategy and anonymity policy. A ReviewTask says that one reviewer
Party reviews one Submission's revision in that round. Both sides are Parties, so nothing
here cares whether people review groups, groups review people, or anything else.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import NewType

from previewit.domain.anonymity import AnonymityPolicy
from previewit.domain.calls import CallId, SubmissionId
from previewit.domain.party import Party
from previewit.domain.tenancy import OrgId, SpaceId

RoundId = NewType("RoundId", str)
TaskId = NewType("TaskId", str)

MAX_PER_SUBMISSION = 20


class InvalidRound(ValueError):
    pass


def clean_per_submission(value: int) -> int:
    if not 1 <= value <= MAX_PER_SUBMISSION:
        raise InvalidRound(f"Each submission needs between 1 and {MAX_PER_SUBMISSION} reviews.")
    return value


# The ways identities can be hidden, by name. M6 applies them; a round just records the choice.
ANONYMITY_PRESETS: dict[str, tuple[str, AnonymityPolicy]] = {
    "reviewers_hidden": (
        "Authors do not see who reviewed them",
        AnonymityPolicy.reviewers_hidden(),
    ),
    "double_anonymous": ("Neither side sees the other", AnonymityPolicy.double_anonymous()),
    "authors_hidden": (
        "Reviewers do not see who wrote the work",
        AnonymityPolicy.authors_hidden(),
    ),
    "open": ("Everyone sees everyone", AnonymityPolicy.open()),
}
DEFAULT_ANONYMITY = "reviewers_hidden"  # PLAN: default = reviewer hidden from author


def anonymity_policy(key: str) -> AnonymityPolicy:
    try:
        return ANONYMITY_PRESETS[key][1]
    except KeyError:
        raise InvalidRound("Choose one of the anonymity options.") from None


class RoundStatus(StrEnum):
    SCHEDULED = "scheduled"  # not open yet
    OPEN = "open"
    CLOSED = "closed"


@dataclass(frozen=True)
class ReviewRound:
    id: RoundId
    org_id: OrgId
    space_id: SpaceId
    call_id: CallId
    number: int
    per_submission: int
    strategy_key: str
    anonymity_key: str
    opens_at: datetime | None
    closes_at: datetime | None

    def status(self, now: datetime) -> RoundStatus:
        if self.opens_at is not None and now < self.opens_at:
            return RoundStatus.SCHEDULED
        if self.closes_at is not None and now >= self.closes_at:
            return RoundStatus.CLOSED
        return RoundStatus.OPEN

    @property
    def anonymity(self) -> AnonymityPolicy:
        return anonymity_policy(self.anonymity_key)


def validate_window(opens_at: datetime | None, closes_at: datetime | None) -> None:
    if opens_at and closes_at and closes_at <= opens_at:
        raise InvalidRound("A round must close after it opens.")


@dataclass(frozen=True)
class ReviewTask:
    id: TaskId
    org_id: OrgId
    space_id: SpaceId
    round_id: RoundId
    reviewer: Party
    submission_id: SubmissionId
    revision_number: int  # the revision reviewers see: the latest when the task was made
    manual: bool  # added by hand, as opposed to produced by a strategy
