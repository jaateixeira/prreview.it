"""Ports: what the application layer needs from the outside world."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from previewit.domain.identity import Email, IdentityKey, User, UserId
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
