"""AI reviews (ADR 0025): feedback written by an AI model on one revision of a Submission.

An AI review is not a Review. No Party writes it, it follows no rubric and no Round, and only
the Submission's author and the organizers of its Space see it. Human reviewers never do.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import NewType

from previewit.domain.calls import SubmissionId
from previewit.domain.identity import UserId
from previewit.domain.tenancy import OrgId

AiReviewId = NewType("AiReviewId", str)

MAX_TEXT = 60_000  # characters of review kept: far more than a review needs
MAX_PROBLEM = 500
MAX_NOTE = 2_000


class AiReviewStatus(StrEnum):
    WAITING = "waiting"  # in the queue
    WRITING = "writing"  # the model is reading and writing
    DONE = "done"
    FAILED = "failed"


class Payer(StrEnum):
    """Who pays the model's service for this review."""

    FREE = "free"  # a model on Previewit's own server
    OWN_KEY = "own_key"  # the person's own key, used for this one request and never kept
    CREDIT = "credit"  # Previewit's key, paid from the person's credit (ADR 0026)


@dataclass(frozen=True)
class AiReview:
    id: AiReviewId
    org_id: OrgId
    submission_id: SubmissionId
    revision: int  # the revision the model reads
    model_key: str
    model_name: str  # kept, so the page still names it if the catalogue changes
    hosted_in: str  # where the model ran: a country code, "" if it varies
    hosting: str
    payer: Payer
    requested_by: UserId
    requested_at: datetime
    note: str = ""  # a few words from the person who asked, given to the model
    status: AiReviewStatus = AiReviewStatus.WAITING
    finished_at: datetime | None = None
    text: str = ""
    problem: str = ""  # why it failed, in words for the person
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: Decimal = Decimal(0)  # what the model's service charged
    credit_cents: int = 0  # paid with credit: held while written, then what it took

    @property
    def finished(self) -> bool:
        return self.status in (AiReviewStatus.DONE, AiReviewStatus.FAILED)

    def writing(self) -> AiReview:
        return replace(self, status=AiReviewStatus.WRITING)

    def waiting(self) -> AiReview:
        return replace(self, status=AiReviewStatus.WAITING)

    def done(
        self, text: str, input_tokens: int, output_tokens: int, cost: Decimal, at: datetime
    ) -> AiReview:
        return replace(
            self,
            status=AiReviewStatus.DONE,
            finished_at=at,
            text=text.strip()[:MAX_TEXT],
            problem="",
            input_tokens=max(input_tokens, 0),
            output_tokens=max(output_tokens, 0),
            cost_usd=max(cost, Decimal(0)),
        )

    def failed(self, problem: str, at: datetime) -> AiReview:
        return replace(
            self,
            status=AiReviewStatus.FAILED,
            finished_at=at,
            problem=(problem.strip() or "The model could not write the review.")[:MAX_PROBLEM],
            credit_cents=0,  # a failed review costs nothing
        )
