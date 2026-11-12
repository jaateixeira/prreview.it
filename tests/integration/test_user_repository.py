"""One contract, run against every UserRepository implementation."""

import os

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine

from previewit.adapters.persistence.memory import InMemoryUserRepository
from previewit.adapters.persistence.migrate import upgrade
from previewit.adapters.persistence.sql import SqlUserRepository
from previewit.adapters.persistence.tables import metadata
from previewit.application.ports import DuplicateEmail, DuplicateIdentity, UserRepository
from previewit.domain.identity import Email, IdentityKey, Provider, User, UserId

POSTGRES_URL = os.environ.get("PREVIEWIT_TEST_POSTGRES_URL")


def _clean_postgres(url: str) -> None:
    engine = create_engine(url)
    with engine.begin() as conn:  # wipe everything, so new tables never need listing here
        conn.exec_driver_sql("DROP SCHEMA public CASCADE")
        conn.exec_driver_sql("CREATE SCHEMA public")
    engine.dispose()


@pytest.fixture(params=["memory", "sqlite", "postgres"])
def repo(request: pytest.FixtureRequest, tmp_path) -> UserRepository:
    if request.param == "memory":
        return InMemoryUserRepository()
    if request.param == "sqlite":
        url = f"sqlite:///{tmp_path / 'test.db'}"
    else:
        if not POSTGRES_URL:
            pytest.skip("set PREVIEWIT_TEST_POSTGRES_URL to run against PostgreSQL")
        _clean_postgres(POSTGRES_URL)
        url = POSTGRES_URL
    upgrade(url)
    engine = create_engine(url)
    request.addfinalizer(engine.dispose)
    return SqlUserRepository(engine)


GOOGLE = IdentityKey(Provider.GOOGLE, "g-1")
APPLE = IdentityKey(Provider.APPLE, "a-1")


def _user(uid="u1", email: str | None = "a@x.fi", *, verified=False, identities=()):
    return User(
        UserId(uid),
        "Ann",
        Email(email) if email else None,
        verified,
        frozenset(identities),
        False,
    )


def test_add_and_find(repo: UserRepository):
    repo.add_user(_user(identities=[GOOGLE]), None)
    assert repo.get(UserId("u1")) == _user(identities=[GOOGLE])
    assert repo.find_by_identity(GOOGLE) == repo.get(UserId("u1"))
    assert repo.find_by_email(Email("A@X.fi")) == repo.get(UserId("u1"))
    assert repo.find_by_identity(APPLE) is None
    assert repo.find_by_email(Email("z@x.fi")) is None
    assert repo.get(UserId("nope")) is None


def test_password_hash_roundtrip_and_has_password(repo: UserRepository):
    repo.add_user(_user(), "hash-1")
    assert repo.get_password_hash(UserId("u1")) == "hash-1"
    user = repo.get(UserId("u1"))
    assert user is not None and user.has_password
    repo.set_password_hash(UserId("u1"), "hash-2")
    assert repo.get_password_hash(UserId("u1")) == "hash-2"


def test_user_without_password_has_no_hash(repo: UserRepository):
    repo.add_user(_user(), None)
    assert repo.get_password_hash(UserId("u1")) is None
    user = repo.get(UserId("u1"))
    assert user is not None and not user.has_password


def test_duplicate_email_is_rejected_case_insensitively(repo: UserRepository):
    repo.add_user(_user("u1", "a@x.fi"), None)
    with pytest.raises(DuplicateEmail):
        repo.add_user(_user("u2", "A@X.FI"), None)


def test_many_users_may_have_no_email(repo: UserRepository):
    repo.add_user(_user("u1", None, identities=[GOOGLE]), None)
    repo.add_user(_user("u2", None, identities=[APPLE]), None)
    assert repo.get(UserId("u2")) is not None


def test_duplicate_identity_is_rejected(repo: UserRepository):
    repo.add_user(_user("u1", "a@x.fi", identities=[GOOGLE]), None)
    with pytest.raises(DuplicateIdentity):
        repo.add_user(_user("u2", "b@x.fi", identities=[GOOGLE]), None)
    assert repo.get(UserId("u2")) is None


def test_add_identity_links_and_can_verify_and_clear_password(repo: UserRepository):
    repo.add_user(_user(), "hash-1")
    repo.add_identity(UserId("u1"), GOOGLE, clear_password=True, verify_email=True)
    user = repo.get(UserId("u1"))
    assert user is not None
    assert user.identities == frozenset({GOOGLE})
    assert user.email_verified and not user.has_password
    assert repo.get_password_hash(UserId("u1")) is None
    assert repo.find_by_identity(GOOGLE) == user


def test_add_identity_keeps_password_by_default(repo: UserRepository):
    repo.add_user(_user(), "hash-1")
    repo.add_identity(UserId("u1"), GOOGLE)
    user = repo.get(UserId("u1"))
    assert user is not None and user.has_password and not user.email_verified


def test_add_identity_twice_is_rejected(repo: UserRepository):
    repo.add_user(_user("u1", "a@x.fi"), None)
    repo.add_user(_user("u2", "b@x.fi"), None)
    repo.add_identity(UserId("u1"), GOOGLE)
    with pytest.raises(DuplicateIdentity):
        repo.add_identity(UserId("u2"), GOOGLE)


# --- migrations ---------------------------------------------------------------


def test_migrated_schema_matches_the_table_definitions(tmp_path):
    url = f"sqlite:///{tmp_path / 'm.db'}"
    upgrade(url)
    engine = create_engine(url)
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), metadata)
    engine.dispose()
    assert diff == []


def test_upgrade_is_idempotent(tmp_path):
    url = f"sqlite:///{tmp_path / 'm.db'}"
    upgrade(url)
    upgrade(url)


def test_mark_email_verified_only_for_the_current_email(repo: UserRepository):
    repo.add_user(_user(), None)
    assert not repo.mark_email_verified(UserId("u1"), Email("other@x.fi"))
    assert not repo.mark_email_verified(UserId("nope"), Email("a@x.fi"))
    assert repo.mark_email_verified(UserId("u1"), Email("A@x.fi"))
    user = repo.get(UserId("u1"))
    assert user is not None and user.email_verified
