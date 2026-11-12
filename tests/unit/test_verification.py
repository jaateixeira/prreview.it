from datetime import UTC, datetime, timedelta

import pytest

from previewit.adapters.persistence.memory import (
    InMemoryEmailTokenRepository,
    InMemoryUserRepository,
)
from previewit.application.verification import SendResult, VerificationService
from previewit.domain.identity import Email, User, UserId

T0 = datetime(2026, 11, 12, 12, 0, tzinfo=UTC)


class Outbox:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []

    def send(self, to: str, subject: str, body: str) -> None:
        self.sent.append((to, subject, body))


class Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def users() -> InMemoryUserRepository:
    repo = InMemoryUserRepository()
    repo.add_user(User(UserId("u1"), "Ann", Email("a@x.fi"), False, frozenset(), True), "h")
    return repo


@pytest.fixture
def outbox() -> Outbox:
    return Outbox()


@pytest.fixture
def service(users, outbox, clock) -> VerificationService:
    counter = iter(range(1, 100))
    return VerificationService(
        users,
        InMemoryEmailTokenRepository(),
        outbox,
        "https://prreview.example",
        clock,
        new_token=lambda: f"tok{next(counter)}",
    )


def _user(users: InMemoryUserRepository) -> User:
    user = users.get(UserId("u1"))
    assert user is not None
    return user


def test_send_mails_a_link_and_confirm_verifies(service, users, outbox):
    assert service.send(_user(users)) is SendResult.SENT
    to, _, body = outbox.sent[0]
    assert to == "a@x.fi" and "https://prreview.example/verify?token=tok1" in body
    confirmed = service.confirm("tok1")
    assert confirmed is not None and confirmed.email_verified


def test_a_token_works_once(service, users):
    service.send(_user(users))
    assert service.confirm("tok1") is not None
    assert service.confirm("tok1") is None


def test_unknown_token(service):
    assert service.confirm("nope") is None


def test_token_expires_after_24_hours(service, users, clock):
    service.send(_user(users))
    clock.now = T0 + timedelta(hours=24, seconds=1)
    assert service.confirm("tok1") is None
    assert not _user(users).email_verified


def test_resend_is_rate_limited_and_replaces_the_old_link(service, users, outbox, clock):
    user = _user(users)
    assert service.send(user) is SendResult.SENT
    assert service.send(user) is SendResult.TOO_SOON
    clock.now = T0 + timedelta(seconds=61)
    assert service.send(user) is SendResult.SENT
    assert len(outbox.sent) == 2
    assert service.confirm("tok1") is None  # superseded
    assert service.confirm("tok2") is not None


def test_nothing_to_send_for_verified_or_email_less_users(service, users, outbox):
    service.send(_user(users))
    service.confirm("tok1")
    assert service.send(_user(users)) is SendResult.ALREADY_VERIFIED
    nobody = User(UserId("u2"), "X", None, False, frozenset(), False)
    assert service.send(nobody) is SendResult.NO_EMAIL
    assert len(outbox.sent) == 1


def test_a_link_for_an_old_address_does_not_verify_a_new_one(service, users):
    service.send(_user(users))
    # the account's email changes after the mail went out
    users._users[UserId("u1")] = User(  # type: ignore[attr-defined]
        UserId("u1"), "Ann", Email("new@x.fi"), False, frozenset(), True
    )
    assert service.confirm("tok1") is None
    assert not _user(users).email_verified


def test_only_a_hash_of_the_token_is_stored(service, users):
    service.send(_user(users))
    stored = service._tokens  # type: ignore[attr-defined]
    assert "tok1" not in str(vars(stored))
