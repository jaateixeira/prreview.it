"""Email verification with single-use, expiring, hashed tokens."""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import Callable
from datetime import datetime, timedelta
from enum import Enum
from urllib.parse import quote

from previewit.application.ports import EmailTokenRepository, Mailer, UserRepository
from previewit.domain.identity import User

TOKEN_TTL = timedelta(hours=24)
RESEND_COOLDOWN = timedelta(seconds=60)


class SendResult(Enum):
    SENT = "sent"
    TOO_SOON = "too_soon"
    ALREADY_VERIFIED = "already_verified"
    NO_EMAIL = "no_email"


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class VerificationService:
    def __init__(
        self,
        users: UserRepository,
        tokens: EmailTokenRepository,
        mailer: Mailer,
        base_url: str,
        now: Callable[[], datetime],
        new_token: Callable[[], str] = lambda: secrets.token_urlsafe(32),
    ) -> None:
        self._users = users
        self._tokens = tokens
        self._mailer = mailer
        self._base_url = base_url.rstrip("/")
        self._now = now
        self._new_token = new_token

    def send(self, user: User) -> SendResult:
        if user.email is None:
            return SendResult.NO_EMAIL
        if user.email_verified:
            return SendResult.ALREADY_VERIFIED
        now = self._now()
        last = self._tokens.last_created_at(user.id)
        if last is not None and now - last < RESEND_COOLDOWN:
            return SendResult.TOO_SOON
        token = self._new_token()
        self._tokens.delete_for_user(user.id)  # only the newest link works
        self._tokens.add(hash_token(token), user.id, user.email, now, now + TOKEN_TTL)
        link = f"{self._base_url}/verify?token={quote(token)}"
        self._mailer.send(
            user.email.value,
            "Confirm your email for Previewit",
            f"Hi {user.display_name},\n\nConfirm your email address:\n{link}\n\n"
            "The link works once and expires in 24 hours. "
            "If you did not sign up, ignore this message.\n",
        )
        return SendResult.SENT

    def confirm(self, token: str) -> User | None:
        record = self._tokens.consume(hash_token(token), self._now())
        if record is None:
            return None
        if not self._users.mark_email_verified(record.user_id, record.email):
            return None
        return self._users.get(record.user_id)
