import pytest

from previewit.adapters.cache import MemoryCache, ValkeyCache, make_cache


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def test_memory_cache_expires_entries():
    clock = Clock()
    cache = MemoryCache(clock=clock)
    cache.set("a", "1", 10)
    assert cache.get("a") == "1"
    clock.t += 10
    assert cache.get("a") is None


def test_memory_cache_is_bounded_and_forgets_the_least_recently_used():
    cache = MemoryCache(max_entries=2)
    cache.set("a", "1", 60)
    cache.set("b", "2", 60)
    cache.get("a")  # a is now newer than b
    cache.set("c", "3", 60)
    assert (cache.get("a"), cache.get("b"), cache.get("c")) == ("1", None, "3")


def test_memory_cache_delete_and_overwrite():
    cache = MemoryCache()
    cache.set("a", "1", 60)
    cache.set("a", "2", 60)
    assert cache.get("a") == "2"
    cache.delete("a")
    cache.delete("never-there")
    assert cache.get("a") is None


class BrokenClient:
    def get(self, *_a, **_k):
        raise ConnectionError("down")

    set = delete = get


def test_a_broken_valkey_is_a_miss_not_an_error(logged):
    cache = ValkeyCache(BrokenClient())
    assert cache.get("k") is None
    cache.set("k", "v", 5)
    cache.delete("k")
    assert logged.text.count("WARNING") == 3


class FakeClient:
    def __init__(self) -> None:
        self.data: dict[str, tuple[str, int | None]] = {}

    def get(self, key):
        entry = self.data.get(key)
        return entry[0] if entry else None

    def set(self, key, value, ex=None):
        self.data[key] = (value, ex)

    def delete(self, key):
        self.data.pop(key, None)


def test_valkey_keys_are_namespaced_and_carry_a_ttl():
    client = FakeClient()
    cache = ValkeyCache(client)
    cache.set("user:1", "x", 60)
    assert client.data == {"previewit:user:1": ("x", 60)}
    assert cache.get("user:1") == "x"
    cache.delete("user:1")
    assert cache.get("user:1") is None


def test_make_cache_chooses_by_url():
    assert isinstance(make_cache(None), MemoryCache)
    assert isinstance(make_cache("valkey://localhost:6399/0"), ValkeyCache)  # lazy: no connection
    with pytest.raises(ValueError, match="scheme"):
        make_cache("memcached://localhost")
