"""In-memory repositories: fast fakes that follow the same contract as the SQL ones."""

from __future__ import annotations

from dataclasses import replace

from previewit.application.ports import DuplicateEmail, DuplicateIdentity
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

    def set_password_hash(self, user_id: UserId, password_hash: str) -> None:
        self._hashes[user_id] = password_hash
        self._users[user_id] = replace(self._users[user_id], has_password=True)
