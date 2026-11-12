"""A user repository that keeps recently read users in a cache.

Every request that carries a session cookie looks its user up, so this is the hottest read in
the system. Writes go to the database first, then drop the cached copy.
"""

from __future__ import annotations

import json
from collections.abc import Sequence

from loguru import logger

from previewit.application.ports import Cache, UserRepository
from previewit.domain.identity import Email, IdentityKey, Provider, User, UserId

DEFAULT_TTL_SECONDS = 60


def _key(user_id: str) -> str:
    return f"user:{user_id}"


def dump_user(user: User) -> str:
    return json.dumps(
        {
            "id": user.id,
            "name": user.display_name,
            "email": user.email.value if user.email else None,
            "verified": user.email_verified,
            "identities": sorted([i.provider.value, i.subject] for i in user.identities),
            "password": user.has_password,
        }
    )


def load_user(raw: str) -> User:
    d = json.loads(raw)
    return User(
        UserId(d["id"]),
        d["name"],
        Email(d["email"]) if d["email"] else None,
        bool(d["verified"]),
        frozenset(IdentityKey(Provider(p), s) for p, s in d["identities"]),
        bool(d["password"]),
    )


class CachedUserRepository:
    def __init__(self, inner: UserRepository, cache: Cache, ttl_seconds: int = DEFAULT_TTL_SECONDS):
        self._inner = inner
        self._cache = cache
        self._ttl = ttl_seconds

    def get(self, user_id: UserId) -> User | None:
        raw = self._cache.get(_key(user_id))
        if raw is not None:
            try:
                user = load_user(raw)
            except (ValueError, KeyError, TypeError):
                logger.warning("dropping unreadable cached user {}", user_id)
                self._cache.delete(_key(user_id))
            else:
                logger.trace("user cache hit {}", user_id)
                return user
        user = self._inner.get(user_id)
        if user is not None:  # unknown ids are not cached: nothing to invalidate later
            self._cache.set(_key(user_id), dump_user(user), self._ttl)
        logger.trace("user cache miss {}", user_id)
        return user

    # -- reads that are not hot enough to cache ------------------------------------------------

    def get_many(self, user_ids: Sequence[UserId]) -> dict[UserId, User]:
        return self._inner.get_many(user_ids)

    def find_by_identity(self, key: IdentityKey) -> User | None:
        return self._inner.find_by_identity(key)

    def find_by_email(self, email: Email) -> User | None:
        return self._inner.find_by_email(email)

    def get_password_hash(self, user_id: UserId) -> str | None:
        return self._inner.get_password_hash(user_id)  # secrets never enter the cache

    # -- writes: database first, then forget ---------------------------------------------------

    def add_user(self, user: User, password_hash: str | None) -> None:
        self._inner.add_user(user, password_hash)
        self._cache.delete(_key(user.id))

    def add_identity(
        self,
        user_id: UserId,
        key: IdentityKey,
        *,
        clear_password: bool = False,
        verify_email: bool = False,
    ) -> None:
        self._inner.add_identity(
            user_id, key, clear_password=clear_password, verify_email=verify_email
        )
        self._cache.delete(_key(user_id))

    def set_password_hash(self, user_id: UserId, password_hash: str) -> None:
        self._inner.set_password_hash(user_id, password_hash)
        self._cache.delete(_key(user_id))

    def mark_email_verified(self, user_id: UserId, email: Email) -> bool:
        changed = self._inner.mark_email_verified(user_id, email)
        self._cache.delete(_key(user_id))
        return changed
