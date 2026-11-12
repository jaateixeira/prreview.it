from previewit.adapters.cache import MemoryCache
from previewit.adapters.persistence.cached_users import (
    CachedUserRepository,
    dump_user,
    load_user,
)
from previewit.adapters.persistence.memory import InMemoryUserRepository
from previewit.domain.identity import Email, IdentityKey, Provider, User, UserId

ANN = UserId("ann")


class CountingRepo(InMemoryUserRepository):
    def __init__(self) -> None:
        super().__init__()
        self.reads = 0

    def get(self, user_id):
        self.reads += 1
        return super().get(user_id)


def make():
    inner, cache = CountingRepo(), MemoryCache()
    repo = CachedUserRepository(inner, cache)
    repo.add_user(User(ANN, "Ann", Email("ann@x.fi"), False, frozenset(), True), "hash")
    return repo, inner, cache


def test_a_user_survives_the_round_trip_through_the_cache():
    user = User(
        ANN,
        "Ann Ö",
        Email("ann@x.fi"),
        True,
        frozenset({IdentityKey(Provider.GOOGLE, "sub-1"), IdentityKey(Provider.HAKA, "h")}),
        False,
    )
    assert load_user(dump_user(user)) == user
    nobody = User(ANN, "A", None, False, frozenset(), False)
    assert load_user(dump_user(nobody)) == nobody


def test_the_second_read_does_not_touch_the_database():
    repo, inner, _ = make()
    assert repo.get(ANN).display_name == "Ann"  # type: ignore[union-attr]
    assert repo.get(ANN).display_name == "Ann"  # type: ignore[union-attr]
    assert inner.reads == 1


def test_unknown_users_are_not_cached():
    repo, inner, _ = make()
    assert repo.get(UserId("nope")) is None
    assert repo.get(UserId("nope")) is None
    assert inner.reads == 2


def test_verifying_the_email_is_visible_at_once():
    repo, _, _ = make()
    assert not repo.get(ANN).email_verified  # type: ignore[union-attr]
    assert repo.mark_email_verified(ANN, Email("ann@x.fi"))
    assert repo.get(ANN).email_verified  # type: ignore[union-attr]


def test_linking_an_identity_and_changing_the_password_are_visible_at_once():
    repo, _, _ = make()
    repo.get(ANN)
    repo.add_identity(ANN, IdentityKey(Provider.GOOGLE, "s"), clear_password=True)
    user = repo.get(ANN)
    assert user is not None and IdentityKey(Provider.GOOGLE, "s") in user.identities
    assert not user.has_password


def test_a_corrupt_cache_entry_is_dropped_and_reloaded():
    repo, inner, cache = make()
    cache.set("user:ann", "{not json", 60)
    assert repo.get(ANN).display_name == "Ann"  # type: ignore[union-attr]
    assert inner.reads == 1


def test_password_hashes_never_enter_the_cache():
    repo, _, cache = make()
    repo.get(ANN)
    assert "hash" not in (cache.get("user:ann") or "")
    assert repo.get_password_hash(ANN) == "hash"
