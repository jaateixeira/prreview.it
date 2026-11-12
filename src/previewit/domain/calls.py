"""Calls, submissions, immutable revisions and share links.

A Call asks a Space for work; a Submission is one Party's answer; each Revision is an
immutable version of the artifact. Nothing here knows what kind of artifact it is.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from typing import NewType

from previewit.domain.identity import UserId
from previewit.domain.party import Party
from previewit.domain.tenancy import OrgId, SpaceId

CallId = NewType("CallId", str)
SubmissionId = NewType("SubmissionId", str)

MAX_TITLE_LENGTH = 200
MAX_DESCRIPTION_LENGTH = 5000


class InvalidCall(ValueError):
    pass


def clean_title(value: str) -> str:
    title = " ".join(value.split())
    if not title or len(title) > MAX_TITLE_LENGTH:
        raise InvalidCall(f"a title must be 1-{MAX_TITLE_LENGTH} characters")
    return title


def clean_description(value: str) -> str:
    text = value.replace("\r\n", "\n").strip()
    if len(text) > MAX_DESCRIPTION_LENGTH:
        raise InvalidCall(f"a description may have at most {MAX_DESCRIPTION_LENGTH} characters")
    return text


@dataclass(frozen=True)
class Artifact:
    """The content of one revision. `type_key` names the plugin that understands it."""

    type_key: str
    media_type: str
    content: bytes
    filename: str | None = None

    @property
    def size(self) -> int:
        return len(self.content)

    @property
    def digest(self) -> str:
        return sha256(self.content).hexdigest()


@dataclass(frozen=True)
class Call:
    id: CallId
    org_id: OrgId
    space_id: SpaceId
    title: str
    description: str
    artifact_type: str
    group_work: bool  # False: each person submits; True: each group submits
    closes_at: datetime | None
    published: bool
    created_by: UserId

    def accepting(self, now: datetime) -> bool:
        return self.published and (self.closes_at is None or now < self.closes_at)


@dataclass(frozen=True)
class Submission:
    id: SubmissionId
    org_id: OrgId
    space_id: SpaceId
    call_id: CallId
    author: Party
    title: str
    created_at: datetime


@dataclass(frozen=True)
class Revision:
    """Append-only: a revision is never edited, so annotations can never drift."""

    submission_id: SubmissionId
    org_id: OrgId
    number: int  # 1, 2, 3, ...
    artifact: Artifact
    created_by: UserId
    created_at: datetime


@dataclass(frozen=True)
class RevisionInfo:
    """A revision without its content, for listings."""

    number: int
    media_type: str
    size: int
    digest: str
    filename: str | None
    created_by: UserId
    created_at: datetime


class ShareTarget(StrEnum):
    CALL = "call"
    SUBMISSION = "submission"


@dataclass(frozen=True)
class ShareLink:
    """A link that lets someone with minimal sign-up see one call or one submission.
    `id` is the SHA-256 of the secret in the link."""

    id: str
    org_id: OrgId
    space_id: SpaceId
    target: ShareTarget
    target_id: str
    created_by: UserId
    expires_at: datetime
    revoked: bool

    def usable(self, now: datetime) -> bool:
        return not self.revoked and self.expires_at > now


@dataclass(frozen=True)
class ShareGrant:
    """Someone who opened a share link: may view that target, nothing else."""

    org_id: OrgId
    space_id: SpaceId
    user_id: UserId
    target: ShareTarget
    target_id: str
