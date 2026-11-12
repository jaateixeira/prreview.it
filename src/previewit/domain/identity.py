"""Identity: users, external identities and the account-linking policy.

Pure domain code. Users are global; organisation membership comes later.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal, NewType

UserId = NewType("UserId", str)

MIN_PASSWORD_LENGTH = 10
MAX_PASSWORD_LENGTH = 128
_MAX_EMAIL_LENGTH = 254
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s.]+$")


class InvalidEmail(ValueError):
    """The text is not a usable email address."""


@dataclass(frozen=True)
class Email:
    """A normalised (trimmed, lower-case) email address."""

    value: str

    def __post_init__(self) -> None:
        normalised = self.value.strip().lower()
        if len(normalised) > _MAX_EMAIL_LENGTH or not _EMAIL_RE.match(normalised):
            raise InvalidEmail(f"invalid email: {self.value!r}")
        object.__setattr__(self, "value", normalised)

    @property
    def domain(self) -> str:
        return self.value.rsplit("@", 1)[1]

    def __str__(self) -> str:
        return self.value


class Provider(StrEnum):
    GOOGLE = "google"
    APPLE = "apple"
    HAKA = "haka"


@dataclass(frozen=True)
class IdentityKey:
    """Stable identifier of a person at an external provider."""

    provider: Provider
    subject: str


@dataclass(frozen=True)
class ExternalClaims:
    """What a provider told us after a successful login."""

    provider: Provider
    subject: str
    email: Email | None
    email_verified: bool
    display_name: str | None

    def __post_init__(self) -> None:
        if not self.subject.strip():
            raise ValueError("subject must not be empty")
        if self.email_verified and self.email is None:
            raise ValueError("a verified email claim needs an email")

    @property
    def key(self) -> IdentityKey:
        return IdentityKey(self.provider, self.subject)


@dataclass(frozen=True)
class User:
    id: UserId
    display_name: str
    email: Email | None
    email_verified: bool
    identities: frozenset[IdentityKey]
    has_password: bool


PasswordProblem = Literal["too_short", "too_long"]


def check_password(password: str) -> PasswordProblem | None:
    """Length is the only rule (NIST 800-63B): no composition requirements."""
    if len(password) < MIN_PASSWORD_LENGTH:
        return "too_short"
    if len(password) > MAX_PASSWORD_LENGTH:
        return "too_long"
    return None


# --- Account-linking policy -------------------------------------------------


@dataclass(frozen=True)
class SignIn:
    user_id: UserId


@dataclass(frozen=True)
class LinkIdentity:
    user_id: UserId
    key: IdentityKey
    reset_password: bool


@dataclass(frozen=True)
class CreateUser:
    key: IdentityKey
    email: Email | None
    email_verified: bool
    display_name: str | None


Decision = SignIn | LinkIdentity | CreateUser


def decide_external_login(
    claims: ExternalClaims,
    *,
    by_identity: User | None,
    by_email: User | None,
) -> Decision:
    """Decide what an external login means for our accounts.

    - A known identity signs in.
    - A provider-verified email equal to an existing account's email links to
      it. If that account never verified its email, whoever registered it
      only claimed the address, so its password is dropped ("claim by
      verification").
    - Anything else creates a user. An unverified email is never stored.
    """
    if by_identity is not None:
        return SignIn(by_identity.id)
    if (
        claims.email_verified
        and by_email is not None
        and by_email.email is not None
        and by_email.email == claims.email
    ):
        return LinkIdentity(
            by_email.id,
            claims.key,
            reset_password=not by_email.email_verified and by_email.has_password,
        )
    trusted = claims.email if claims.email_verified else None
    return CreateUser(claims.key, trusted, claims.email_verified, claims.display_name)
