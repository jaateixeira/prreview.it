"""Ports: what the application layer needs from the outside world."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
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
