"""Caches: Valkey for hosted deployments, an in-process one for development.

A broken Valkey is a cache miss, never an outage: every error is logged and swallowed.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from typing import Any

from loguru import logger

NAMESPACE = "previewit:"


class MemoryCache:
    """Per-process and bounded. Fine for one worker; with several workers use Valkey, or
    entries can be stale for up to their TTL after a change made by another worker."""

    def __init__(
        self, max_entries: int = 10_000, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._items: OrderedDict[str, tuple[float, str]] = OrderedDict()
        self._max = max_entries
        self._clock = clock
        self._lock = threading.Lock()

    def get(self, key: str) -> str | None:
        with self._lock:
            entry = self._items.get(key)
            if entry is None:
                return None
            expires, value = entry
            if expires <= self._clock():
                del self._items[key]
                return None
            self._items.move_to_end(key)
            return value

    def set(self, key: str, value: str, ttl_seconds: int) -> None:
        with self._lock:
            self._items[key] = (self._clock() + ttl_seconds, value)
            self._items.move_to_end(key)
            while len(self._items) > self._max:
                self._items.popitem(last=False)

    def delete(self, key: str) -> None:
        with self._lock:
            self._items.pop(key, None)


class ValkeyCache:
    """Valkey (or any Redis-protocol server) through the `valkey` client."""

    def __init__(self, client: Any) -> None:
        self._client = client

    @classmethod
    def from_url(cls, url: str) -> ValkeyCache:
        try:
            import valkey
        except ImportError:
            raise RuntimeError(
                "a Valkey cache is configured but the client is missing; "
                "install it with: uv sync --extra valkey"
            ) from None
        # Short timeouts: a slow cache must not make the site slower than having none.
        client = valkey.Valkey.from_url(
            url, decode_responses=True, socket_timeout=0.2, socket_connect_timeout=0.5
        )
        return cls(client)

    def get(self, key: str) -> str | None:
        try:
            value = self._client.get(NAMESPACE + key)
        except Exception as error:
            logger.warning("cache get failed, treating as a miss: {}", error)
            return None
        return value if isinstance(value, str) else None

    def set(self, key: str, value: str, ttl_seconds: int) -> None:
        try:
            self._client.set(NAMESPACE + key, value, ex=ttl_seconds)
        except Exception as error:
            logger.warning("cache set failed, continuing without it: {}", error)

    def delete(self, key: str) -> None:
        try:
            self._client.delete(NAMESPACE + key)
        except Exception as error:
            # A stale entry will live until its TTL; the TTL is the safety net.
            logger.warning("cache delete failed, entry expires by TTL: {}", error)


def make_cache(url: str | None):
    """`valkey://`, `redis://` or `rediss://` URL -> Valkey; nothing -> in-process cache."""
    if not url:
        return MemoryCache()
    if url.split("://", 1)[0] not in {"valkey", "valkeys", "redis", "rediss", "unix"}:
        raise ValueError(f"unsupported cache URL scheme in {url.split('@')[-1]!r}")
    return ValkeyCache.from_url(url)
