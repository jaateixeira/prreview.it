"""Ports: what the application layer needs from the outside world."""

from __future__ import annotations

from typing import Protocol

from previewit.domain.identity import Email, IdentityKey, User, UserId


class DuplicateEmail(Exception):
    """Another user already has this email."""


class DuplicateIdentity(Exception):
    """This external identity is already linked to a user."""


class UserRepository(Protocol):
    def get(self, user_id: UserId) -> User | None: ...

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


class PasswordHasher(Protocol):
    def hash(self, password: str) -> str: ...

    def verify(self, password_hash: str, password: str) -> bool: ...

    def needs_rehash(self, password_hash: str) -> bool: ...

    def dummy_hash(self) -> str:
        """A valid hash nobody knows the password of, to equalise login timing."""
        ...
