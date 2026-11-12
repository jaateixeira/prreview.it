"""The call for reviewers: one personal invitation per reviewer (ADR 0017).

An Invitation belongs to one email address and one Round, has its own secret token and
carries the work the reviewer is asked to review. Opening it, with that verified email,
makes the person a Reviewer in the Space and creates their review tasks.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from previewit.domain.calls import SubmissionId
from previewit.domain.identity import Email, UserId
from previewit.domain.rounds import RoundId
from previewit.domain.tenancy import OrgId, SpaceId

MAX_SUBMISSIONS_PER_INVITATION = 50


class InvalidInvitation(ValueError):
    """The organizer asked for something an invitation cannot be."""


def clean_email(value: str) -> Email:
    try:
        return Email(value)
    except ValueError:
        raise InvalidInvitation("Enter the reviewer's email address.") from None


def mask_email(email: Email) -> str:
    """`a***@example.org`: enough to recognise your own address, not to learn someone's."""
    local, _, domain = email.value.partition("@")
    return f"{local[:1]}***@{domain}"


@dataclass(frozen=True)
class Invitation:
    """`id` is the SHA-256 of the secret in the link, as with share links."""

    id: str
    org_id: OrgId
    space_id: SpaceId
    round_id: RoundId
    email: Email
    submission_ids: tuple[SubmissionId, ...]  # the work to review; may be empty
    created_by: UserId
    expires_at: datetime
    revoked: bool
    accepted_by: UserId | None

    def usable(self, now: datetime) -> bool:
        return not self.revoked and self.expires_at > now

    def status(self, now: datetime) -> str:
        if self.revoked:
            return "revoked"
        if self.accepted_by is not None:
            return "accepted"
        return "expired" if self.expires_at <= now else "waiting"
