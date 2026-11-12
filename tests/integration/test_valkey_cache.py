"""ValkeyCache against a real server. Uses PREVIEWIT_TEST_VALKEY_URL, or starts a throwaway
valkey-server / redis-server if one is installed; otherwise skipped."""

import os
import shutil
import socket
import subprocess
import time

import pytest

from previewit.adapters.cache import ValkeyCache
from previewit.adapters.persistence.cached_users import CachedUserRepository
from previewit.adapters.persistence.memory import InMemoryUserRepository
from previewit.domain.identity import Email, User, UserId


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def url(tmp_path_factory):
    configured = os.environ.get("PREVIEWIT_TEST_VALKEY_URL")
    if configured:
        yield configured
        return
    binary = shutil.which("valkey-server") or shutil.which("redis-server")
    if binary is None:
        pytest.skip("no Valkey server: set PREVIEWIT_TEST_VALKEY_URL or install valkey-server")
    port = _free_port()
    proc = subprocess.Popen(
        [binary, "--port", str(port), "--save", "", "--appendonly", "no", "--bind", "127.0.0.1"],
        cwd=tmp_path_factory.mktemp("valkey"),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(50):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.1).close()
            break
        except OSError:
            time.sleep(0.1)
    yield f"valkey://127.0.0.1:{port}/0"
    proc.terminate()
    proc.wait(timeout=5)


def test_round_trip_ttl_and_delete(url):
    cache = ValkeyCache.from_url(url)
    cache.set("k", "v", 60)
    assert cache.get("k") == "v"
    cache.delete("k")
    assert cache.get("k") is None
    cache.set("short", "v", 1)
    time.sleep(1.2)
    assert cache.get("short") is None


def test_a_cache_that_cannot_be_reached_is_just_empty(logged):
    cache = ValkeyCache.from_url(f"valkey://127.0.0.1:{_free_port()}/0")
    assert cache.get("k") is None
    cache.set("k", "v", 5)
    assert "WARNING" in logged.text


def test_cached_users_over_a_real_server_see_changes_at_once(url):
    inner = InMemoryUserRepository()
    repo = CachedUserRepository(inner, ValkeyCache.from_url(url))
    repo.add_user(User(UserId("vk"), "Vk", Email("vk@x.fi"), False, frozenset(), False), None)
    assert not repo.get(UserId("vk")).email_verified  # type: ignore[union-attr]
    repo.mark_email_verified(UserId("vk"), Email("vk@x.fi"))
    assert repo.get(UserId("vk")).email_verified  # type: ignore[union-attr]
