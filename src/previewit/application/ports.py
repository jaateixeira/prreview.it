"""Ports: what the application layer needs from the outside world."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from previewit.domain.calls import (
    Artifact,
    Call,
    CallId,
    Revision,
    RevisionInfo,
    ShareGrant,
    ShareLink,
    ShareTarget,
    Submission,
    SubmissionId,
)
from previewit.domain.identity import Email, IdentityKey, User, UserId
from previewit.domain.party import Party
from previewit.domain.reviews import Annotation, AnnotationId, Review, ReviewEdit, ReviewId
from previewit.domain.rounds import ReviewRound, ReviewTask, RoundId, TaskId
from previewit.domain.rubrics import Criterion, CriterionId, Rubric, RubricId
from previewit.domain.tenancy import (
    Group,
    GroupId,
    Invite,
    Organization,
    OrgId,
    OrgRole,
    Space,
    SpaceId,
    SpaceMember,
)


class DuplicateEmail(Exception):
    """Another user already has this email."""


class DuplicateIdentity(Exception):
    """This external identity is already linked to a user."""


class UserRepository(Protocol):
    def get(self, user_id: UserId) -> User | None: ...

    def get_many(self, user_ids: Sequence[UserId]) -> dict[UserId, User]: ...

    def find_by_identity(self, key: IdentityKey) -> User | None: ...

    def find_by_email(self, email: Email) -> User | None: ...

    def add_user(self, user: User, password_hash: str | None) -> None:
        """Store a new user (with its identities). May raise DuplicateEmail/DuplicateIdentity."""
        ...

    def add_identity(
        self,
        user_id: UserId,
        key: IdentityKey,
        *,
        clear_password: bool = False,
        verify_email: bool = False,
    ) -> None:
        """Link an identity; optionally drop the password and mark the email verified."""
        ...

    def get_password_hash(self, user_id: UserId) -> str | None: ...

    def set_password_hash(self, user_id: UserId, password_hash: str) -> None: ...

    def mark_email_verified(self, user_id: UserId, email: Email) -> bool:
        """Verify the email only if it is still the account's email. True if now verified."""
        ...


class Cache(Protocol):
    """A fast, lossy key-value store for data that is read far more often than it changes.

    Only a copy: the database stays the source of truth. A cache that is down must behave
    like an empty one, never like an error.
    """

    def get(self, key: str) -> str | None: ...

    def set(self, key: str, value: str, ttl_seconds: int) -> None: ...

    def delete(self, key: str) -> None: ...


class PasswordHasher(Protocol):
    def hash(self, password: str) -> str: ...

    def verify(self, password_hash: str, password: str) -> bool: ...

    def needs_rehash(self, password_hash: str) -> bool: ...

    def dummy_hash(self) -> str:
        """A valid hash nobody knows the password of, to equalise login timing."""
        ...


@dataclass(frozen=True)
class EmailToken:
    user_id: UserId
    email: Email


class EmailTokenRepository(Protocol):
    """One-time email verification tokens. Only SHA-256 hashes are stored."""

    def add(
        self,
        token_hash: str,
        user_id: UserId,
        email: Email,
        created_at: datetime,
        expires_at: datetime,
    ) -> None: ...

    def delete_for_user(self, user_id: UserId) -> None: ...

    def last_created_at(self, user_id: UserId) -> datetime | None: ...

    def consume(self, token_hash: str, now: datetime) -> EmailToken | None:
        """Atomically mark an unused, unexpired token as used and return it."""
        ...


class Mailer(Protocol):
    def send(self, to: str, subject: str, body: str) -> None:
        """Send a plain-text mail. Raises MailError on failure."""
        ...


class MailError(Exception):
    pass


class TenancyRepository(Protocol):
    """Organizations, spaces, memberships, groups and invites.

    Every row carries its org_id. Callers authorise first; ids of other tenants
    simply are not found.
    """

    # organizations
    def add_org(self, org: Organization, owner: UserId) -> None: ...
    def get_org(self, org_id: OrgId) -> Organization | None: ...
    def org_role(self, org_id: OrgId, user_id: UserId) -> OrgRole | None: ...
    def add_org_member(self, org_id: OrgId, user_id: UserId, role: OrgRole) -> None:
        """Idempotent: an existing membership (and its role) is kept."""
        ...

    def orgs_for_user(self, user_id: UserId) -> list[tuple[Organization, OrgRole]]: ...

    # spaces
    def add_space(self, space: Space, creator: SpaceMember) -> None: ...
    def get_space(self, space_id: SpaceId) -> Space | None: ...
    def spaces_in_org(self, org_id: OrgId) -> list[Space]: ...
    def spaces_of_member(self, org_id: OrgId, user_id: UserId) -> list[Space]: ...
    def spaces_for_user(self, user_id: UserId) -> list[Space]:
        """Spaces the user is a member of, across organizations."""
        ...

    def space_member(self, space_id: SpaceId, user_id: UserId) -> SpaceMember | None: ...
    def space_members(self, space_id: SpaceId) -> list[SpaceMember]: ...
    def add_space_member(self, member: SpaceMember) -> None:
        """Idempotent: an existing membership (and its role) is kept."""
        ...

    def set_space_member_role(self, space_id: SpaceId, user_id: UserId, role_key: str) -> None: ...
    def remove_space_member(self, space_id: SpaceId, user_id: UserId) -> None:
        """Also removes the user from every group of the space."""
        ...

    # groups
    def add_group(self, group: Group) -> None: ...
    def get_group(self, group_id: GroupId) -> Group | None: ...
    def groups_in_space(self, space_id: SpaceId) -> list[Group]: ...
    def rename_group(self, group_id: GroupId, name: str) -> None: ...
    def delete_group(self, group_id: GroupId) -> None: ...
    def add_group_member(self, group_id: GroupId, user_id: UserId) -> None: ...
    def remove_group_member(self, group_id: GroupId, user_id: UserId) -> None: ...

    # invites (stored by the hash of their secret)
    def add_invite(self, invite: Invite) -> None: ...
    def get_invite(self, invite_id: str) -> Invite | None: ...
    def invites_in_space(self, space_id: SpaceId) -> list[Invite]: ...
    def revoke_invite(self, invite_id: str) -> None: ...
    def use_invite(self, invite_id: str, now: datetime) -> bool:
        """Atomically count one use if the invite is still usable. False if not."""
        ...


class DuplicateSubmission(Exception):
    """This party already has a submission for this call."""


class DuplicateRound(Exception):
    """A round with that number already exists for the call (two organizers at once)."""


class DuplicateReview(Exception):
    """This task already has a review."""


class DuplicateTask(Exception):
    """That reviewer already has that submission in the round."""


class CallRepository(Protocol):
    """Calls, submissions, revisions and share links. Rows carry org_id; callers authorise first."""

    def add_call(self, call: Call) -> None: ...

    def get_call(self, call_id: CallId) -> Call | None: ...

    def update_call(self, call: Call) -> None: ...

    def delete_call(self, call_id: CallId) -> None: ...

    def calls_in_space(self, space_id: SpaceId) -> list[Call]: ...

    def calls_using_rubric(self, rubric_id: RubricId) -> list[Call]: ...

    def add_submission(
        self, submission: Submission, artifact: Artifact, created_by: UserId, now: datetime
    ) -> Revision:
        """Store the submission and its revision 1 together. May raise DuplicateSubmission."""
        ...

    def get_submission(self, submission_id: SubmissionId) -> Submission | None: ...

    def submissions_in_call(self, call_id: CallId) -> list[Submission]: ...

    def submissions_of_parties(
        self, call_id: CallId, parties: Sequence[Party]
    ) -> list[Submission]: ...

    def add_revision(
        self, submission_id: SubmissionId, artifact: Artifact, created_by: UserId, now: datetime
    ) -> Revision:
        """Append the next revision (numbers are 1, 2, 3, ... without gaps)."""
        ...

    def revision_infos(self, submission_id: SubmissionId) -> list[RevisionInfo]: ...

    def get_revision(self, submission_id: SubmissionId, number: int) -> Revision | None: ...

    def add_share_link(self, link: ShareLink) -> None: ...

    def get_share_link(self, link_id: str) -> ShareLink | None: ...

    def share_links_for(self, target: ShareTarget, target_id: str) -> list[ShareLink]: ...

    def revoke_share_link(self, link_id: str) -> None: ...

    def count_share_links(self, created_by: UserId) -> int: ...

    def add_share_grant(self, grant: ShareGrant) -> None:
        """Idempotent."""
        ...

    def has_share_grant(self, user_id: UserId, target: ShareTarget, target_id: str) -> bool: ...

    def share_grants_for(self, user_id: UserId) -> list[ShareGrant]: ...


class Entitlements(Protocol):
    """What a user's plan allows. Limits are decided here, never by `if plan == ...`."""

    def may_create_share(self, user_id: UserId, shares_so_far: int) -> bool: ...


class RubricRepository(Protocol):
    """Rubrics and their criteria. Rows carry org_id; callers authorise first."""

    def add_rubric(self, rubric: Rubric, items: Sequence[Criterion] = ()) -> None: ...

    def get_rubric(self, rubric_id: RubricId) -> Rubric | None: ...

    def update_rubric(self, rubric: Rubric) -> None: ...

    def delete_rubric(self, rubric_id: RubricId) -> None: ...

    def rubrics_in_space(self, space_id: SpaceId) -> list[Rubric]: ...

    def add_criterion(self, criterion: Criterion) -> None: ...

    def get_criterion(self, criterion_id: CriterionId) -> Criterion | None: ...

    def update_criterion(self, criterion: Criterion) -> None: ...

    def delete_criterion(self, criterion_id: CriterionId) -> None: ...

    def criteria_of(self, rubric_id: RubricId) -> list[Criterion]:
        """In display order."""
        ...

    def set_positions(self, rubric_id: RubricId, order: Sequence[CriterionId]) -> None:
        """Renumber the rubric's criteria 0, 1, 2, ... in this order."""
        ...


class RoundRepository(Protocol):
    """Review rounds and their tasks. Rows carry org_id; callers authorise first."""

    def add_round(self, round_: ReviewRound) -> None: ...

    def get_round(self, round_id: RoundId) -> ReviewRound | None: ...

    def update_round(self, round_: ReviewRound) -> None: ...

    def delete_round(self, round_id: RoundId) -> None: ...

    def rounds_of_call(self, call_id: CallId) -> list[ReviewRound]:
        """Ordered by number."""
        ...

    def add_tasks(self, tasks: Sequence[ReviewTask]) -> None: ...

    def replace_tasks(self, round_id: RoundId, tasks: Sequence[ReviewTask]) -> None:
        """Atomically swap every task of the round for these."""
        ...

    def get_task(self, task_id: TaskId) -> ReviewTask | None: ...

    def delete_task(self, task_id: TaskId) -> None: ...

    def tasks_of_round(self, round_id: RoundId) -> list[ReviewTask]: ...

    def tasks_for_parties(self, space_id: SpaceId, parties: Sequence[Party]) -> list[ReviewTask]:
        """Tasks in the space whose reviewer is one of these parties."""
        ...


class ReviewRepository(Protocol):
    """Reviews, their edit trail and annotations. Rows carry org_id; callers authorise first."""

    def get_review(self, review_id: ReviewId) -> Review | None: ...

    def review_of_task(self, task_id: TaskId) -> Review | None: ...

    def add_review(self, review: Review, edit: ReviewEdit) -> None:
        """Raises DuplicateReview if the task already has one."""
        ...

    def update_review(self, review: Review, expected_version: int, edit: ReviewEdit) -> bool:
        """Save only if the stored version is still `expected_version`; False if it moved."""
        ...

    def reviews_in_round(self, round_id: RoundId) -> list[Review]: ...

    def edits_of(self, review_id: ReviewId) -> list[ReviewEdit]:
        """Oldest first."""
        ...

    def add_annotation(self, annotation: Annotation) -> None: ...

    def get_annotation(self, annotation_id: AnnotationId) -> Annotation | None: ...

    def delete_annotation(self, annotation_id: AnnotationId) -> None: ...

    def annotations_of(self, review_id: ReviewId) -> list[Annotation]:
        """Oldest first."""
        ...
