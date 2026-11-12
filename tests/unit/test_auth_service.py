from itertools import count

import pytest

from previewit.adapters.persistence.memory import InMemoryUserRepository
from previewit.application.auth import (
    AuthService,
    EmailTaken,
    InvalidCredentials,
    WeakPassword,
)
from previewit.domain.identity import Email, ExternalClaims, InvalidEmail, Provider


class FakeHasher:
    def hash(self, password: str) -> str:
        return f"h:{password}"

    def verify(self, password_hash: str, password: str) -> bool:
        return password_hash in (f"h:{password}", f"old:{password}")

    def needs_rehash(self, password_hash: str) -> bool:
        return password_hash.startswith("old:")

    def dummy_hash(self) -> str:
        return "h:never-matches-a-real-password-!"


@pytest.fixture
def repo() -> InMemoryUserRepository:
    return InMemoryUserRepository()


@pytest.fixture
def auth(repo: InMemoryUserRepository) -> AuthService:
    ids = count(1)
    return AuthService(repo, FakeHasher(), lambda: f"u{next(ids)}")


def _claims(email="a@x.fi", verified=True, subject="s1", provider=Provider.GOOGLE):
    return ExternalClaims(provider, subject, Email(email) if email else None, verified, "Ann")


# --- password registration / login ------------------------------------------


def test_register_then_login(auth: AuthService):
    user = auth.register_with_password("Ann@X.fi", "correct horse battery", "Ann")
    assert user.email == Email("ann@x.fi")
    assert user.has_password and not user.email_verified
    assert auth.login_with_password("ann@x.fi", "correct horse battery").id == user.id


def test_register_rejects_bad_input(auth: AuthService):
    with pytest.raises(InvalidEmail):
        auth.register_with_password("nope", "correct horse battery", "Ann")
    with pytest.raises(WeakPassword):
        auth.register_with_password("a@x.fi", "short", "Ann")


def test_register_twice_with_the_same_email_fails(auth: AuthService):
    auth.register_with_password("a@x.fi", "correct horse battery", "Ann")
    with pytest.raises(EmailTaken):
        auth.register_with_password("A@x.fi", "another long password", "Ann 2")


def test_wrong_password_and_unknown_email_look_the_same(auth: AuthService):
    auth.register_with_password("a@x.fi", "correct horse battery", "Ann")
    with pytest.raises(InvalidCredentials):
        auth.login_with_password("a@x.fi", "wrong wrong wrong")
    with pytest.raises(InvalidCredentials):
        auth.login_with_password("nobody@x.fi", "correct horse battery")
    with pytest.raises(InvalidCredentials):
        auth.login_with_password("not-an-email", "correct horse battery")


def test_external_only_account_cannot_log_in_with_a_password(auth: AuthService):
    auth.login_with_external(_claims())
    with pytest.raises(InvalidCredentials):
        auth.login_with_password("a@x.fi", "")


def test_login_upgrades_an_outdated_hash(auth: AuthService, repo: InMemoryUserRepository):
    user = auth.register_with_password("a@x.fi", "correct horse battery", "Ann")
    repo.set_password_hash(user.id, "old:correct horse battery")
    auth.login_with_password("a@x.fi", "correct horse battery")
    assert repo.get_password_hash(user.id) == "h:correct horse battery"


# --- external login ----------------------------------------------------------


def test_first_external_login_creates_a_user_and_the_second_signs_in(auth: AuthService):
    first = auth.login_with_external(_claims())
    assert first.email == Email("a@x.fi") and first.email_verified
    second = auth.login_with_external(_claims(email="changed@x.fi"))
    assert second.id == first.id


def test_external_login_links_to_the_account_with_the_same_verified_email(auth: AuthService):
    pw_user = auth.register_with_password("a@x.fi", "correct horse battery", "Ann")
    user = auth.login_with_external(_claims())
    assert user.id == pw_user.id
    assert user.email_verified  # the provider vouched for the address
    # password sign-ups are unverified until the email flow exists, so the password goes
    assert not user.has_password
    # and the identity stuck
    assert auth.login_with_external(_claims()).id == pw_user.id


def test_claim_by_verification_drops_a_squatters_password(auth: AuthService):
    squatter = auth.register_with_password("victim@x.fi", "attacker chosen pw", "Mallory")
    user = auth.login_with_external(_claims(email="victim@x.fi"))
    assert user.id == squatter.id
    assert not user.has_password
    with pytest.raises(InvalidCredentials):
        auth.login_with_password("victim@x.fi", "attacker chosen pw")


def test_unverified_external_email_creates_a_separate_account(auth: AuthService):
    pw_user = auth.register_with_password("a@x.fi", "correct horse battery", "Ann")
    user = auth.login_with_external(_claims(verified=False))
    assert user.id != pw_user.id
    assert user.email is None and not user.email_verified


def test_same_subject_at_different_providers_are_different_people(auth: AuthService):
    google = auth.login_with_external(_claims(provider=Provider.GOOGLE, email="g@x.fi"))
    apple = auth.login_with_external(_claims(provider=Provider.APPLE, email="p@x.fi"))
    assert google.id != apple.id


def test_get_user(auth: AuthService):
    user = auth.login_with_external(_claims())
    assert auth.get_user(user.id) == user
    assert auth.get_user("missing") is None  # type: ignore[arg-type]
