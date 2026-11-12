"""In-memory repositories: fast fakes that follow the same contract as the SQL ones."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from previewit.application.ports import DuplicateEmail, DuplicateIdentity, EmailToken
from previewit.domain.identity import Email, IdentityKey, User, UserId


class InMemoryUserRepository:
    def __init__(self) -> None:
        self._users: dict[UserId, User] = {}
        self._hashes: dict[UserId, str] = {}
        self._by_identity: dict[IdentityKey, UserId] = {}

    def get(self, user_id: UserId) -> User | None:
        return self._users.get(user_id)

    def find_by_identity(self, key: IdentityKey) -> User | None:
        user_id = self._by_identity.get(key)
        return self._users[user_id] if user_id else None

    def find_by_email(self, email: Email) -> User | None:
        return next((u for u in self._users.values() if u.email == email), None)

    def add_user(self, user: User, password_hash: str | None) -> None:
        if user.email is not None and self.find_by_email(user.email) is not None:
            raise DuplicateEmail
        if any(key in self._by_identity for key in user.identities):
            raise DuplicateIdentity
        self._users[user.id] = replace(user, has_password=password_hash is not None)
        if password_hash is not None:
            self._hashes[user.id] = password_hash
        for key in user.identities:
            self._by_identity[key] = user.id

    def add_identity(
        self,
        user_id: UserId,
        key: IdentityKey,
        *,
        clear_password: bool = False,
        verify_email: bool = False,
    ) -> None:
        if key in self._by_identity:
            raise DuplicateIdentity
        user = self._users[user_id]
        if clear_password:
            self._hashes.pop(user_id, None)
        self._users[user_id] = replace(
            user,
            identities=user.identities | {key},
            has_password=user_id in self._hashes,
            email_verified=user.email_verified or (verify_email and user.email is not None),
        )
        self._by_identity[key] = user_id

    def get_password_hash(self, user_id: UserId) -> str | None:
        return self._hashes.get(user_id)

    def mark_email_verified(self, user_id: UserId, email: Email) -> bool:
        user = self._users.get(user_id)
        if user is None or user.email != email:
            return False
        self._users[user_id] = replace(user, email_verified=True)
        return True

    def set_password_hash(self, user_id: UserId, password_hash: str) -> None:
        self._hashes[user_id] = password_hash
        self._users[user_id] = replace(self._users[user_id], has_password=True)


class InMemoryEmailTokenRepository:
    def __init__(self) -> None:
        # hash -> (user, email, created, expires, used)
        self._rows: dict[str, tuple[UserId, Email, datetime, datetime, bool]] = {}

    def add(
        self,
        token_hash: str,
        user_id: UserId,
        email: Email,
        created_at: datetime,
        expires_at: datetime,
    ) -> None:
        self._rows[token_hash] = (user_id, email, created_at, expires_at, False)

    def delete_for_user(self, user_id: UserId) -> None:
        self._rows = {h: r for h, r in self._rows.items() if r[0] != user_id}

    def last_created_at(self, user_id: UserId) -> datetime | None:
        times = [r[2] for r in self._rows.values() if r[0] == user_id]
        return max(times) if times else None

    def consume(self, token_hash: str, now: datetime) -> EmailToken | None:
        row = self._rows.get(token_hash)
        if row is None or row[4] or row[3] <= now:
            return None
        self._rows[token_hash] = (*row[:4], True)
        return EmailToken(row[0], row[1])
