"""Contract for EmailTokenRepository across in-memory, SQLite and PostgreSQL."""

import os
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine

from previewit.adapters.persistence.memory import (
    InMemoryEmailTokenRepository,
)
from previewit.adapters.persistence.migrate import upgrade
from previewit.adapters.persistence.sql import SqlEmailTokenRepository, SqlUserRepository
from previewit.application.ports import EmailToken, EmailTokenRepository
from previewit.domain.identity import Email, User, UserId
from tests.integration.test_user_repository import _clean_postgres

POSTGRES_URL = os.environ.get("PREVIEWIT_TEST_POSTGRES_URL")
T0 = datetime(2026, 11, 12, 12, 0, tzinfo=UTC)
U1, U2 = UserId("u1"), UserId("u2")


@pytest.fixture(params=["memory", "sqlite", "postgres"])
def tokens(request: pytest.FixtureRequest, tmp_path) -> EmailTokenRepository:
    if request.param == "memory":
        return InMemoryEmailTokenRepository()
    if request.param == "sqlite":
        url = f"sqlite:///{tmp_path / 't.db'}"
    else:
        if not POSTGRES_URL:
            pytest.skip("set PREVIEWIT_TEST_POSTGRES_URL to run against PostgreSQL")
        _clean_postgres(POSTGRES_URL)
        url = POSTGRES_URL
    upgrade(url)
    engine = create_engine(url)
    request.addfinalizer(engine.dispose)
    users = SqlUserRepository(engine)
    for uid, mail in ((U1, "a@x.fi"), (U2, "b@x.fi")):
        users.add_user(User(uid, "N", Email(mail), False, frozenset(), False), None)
    return SqlEmailTokenRepository(engine)


def _add(tokens: EmailTokenRepository, h="h1", uid=U1, mail="a@x.fi", ttl=timedelta(hours=1)):
    tokens.add(h, uid, Email(mail), T0, T0 + ttl)


def test_consume_returns_the_record_once(tokens: EmailTokenRepository):
    _add(tokens)
    assert tokens.consume("h1", T0 + timedelta(minutes=1)) == EmailToken(U1, Email("a@x.fi"))
    assert tokens.consume("h1", T0 + timedelta(minutes=2)) is None


def test_expired_and_unknown_tokens_are_not_consumable(tokens: EmailTokenRepository):
    _add(tokens)
    assert tokens.consume("h1", T0 + timedelta(hours=1)) is None
    assert tokens.consume("missing", T0) is None


def test_delete_for_user_only_touches_that_user(tokens: EmailTokenRepository):
    _add(tokens, "h1", U1)
    _add(tokens, "h2", U2, "b@x.fi")
    tokens.delete_for_user(U1)
    assert tokens.consume("h1", T0) is None
    assert tokens.consume("h2", T0) is not None


def test_last_created_at(tokens: EmailTokenRepository):
    assert tokens.last_created_at(U1) is None
    _add(tokens)
    assert tokens.last_created_at(U1) == T0
    assert tokens.last_created_at(U2) is None
