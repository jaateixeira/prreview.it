import pytest
from hypothesis import given
from hypothesis import strategies as st

from previewit.domain.identity import (
    CreateUser,
    Email,
    ExternalClaims,
    IdentityKey,
    InvalidEmail,
    LinkIdentity,
    Provider,
    SignIn,
    User,
    UserId,
    check_password,
    decide_external_login,
)

# --- Email ------------------------------------------------------------------


def test_email_is_normalised():
    assert Email("  Jose.Teixeira@JYU.fi ").value == "jose.teixeira@jyu.fi"


@pytest.mark.parametrize(
    "bad", ["", "no-at-sign", "a@b", "a b@c.fi", "@c.fi", "a@@c.fi", "x" * 250 + "@c.fi"]
)
def test_invalid_emails_are_rejected(bad: str):
    with pytest.raises(InvalidEmail):
        Email(bad)


def test_email_domain():
    assert Email("a@student.jyu.fi").domain == "student.jyu.fi"


# --- Password rule ----------------------------------------------------------


def test_password_length_is_the_only_rule():
    assert check_password("short") == "too_short"
    assert check_password("x" * 129) == "too_long"
    assert check_password("a" * 10) is None
    assert check_password("correct horse battery staple") is None


# --- Claims -----------------------------------------------------------------


def test_claims_need_a_subject():
    with pytest.raises(ValueError):
        ExternalClaims(Provider.GOOGLE, " ", None, False, None)


def test_verified_email_claim_needs_an_email():
    with pytest.raises(ValueError):
        ExternalClaims(Provider.GOOGLE, "sub", None, True, None)


# --- Linking policy ---------------------------------------------------------


def _claims(
    *,
    email: str | None = "a@x.fi",
    verified: bool = True,
    subject: str = "s1",
    provider: Provider = Provider.GOOGLE,
) -> ExternalClaims:
    return ExternalClaims(provider, subject, Email(email) if email else None, verified, "A")


def _user(uid: str, email: str | None, *, verified: bool, has_password: bool = False) -> User:
    return User(
        UserId(uid), "A", Email(email) if email else None, verified, frozenset(), has_password
    )


def test_known_identity_signs_in():
    user = _user("u1", "a@x.fi", verified=True)
    decision = decide_external_login(_claims(), by_identity=user, by_email=None)
    assert decision == SignIn(user.id)


def test_unknown_identity_creates_a_user():
    decision = decide_external_login(_claims(), by_identity=None, by_email=None)
    assert decision == CreateUser(IdentityKey(Provider.GOOGLE, "s1"), Email("a@x.fi"), True, "A")


def test_verified_email_links_to_the_verified_account_with_the_same_email():
    existing = _user("u1", "a@x.fi", verified=True, has_password=True)
    decision = decide_external_login(_claims(), by_identity=None, by_email=existing)
    assert decision == LinkIdentity(
        existing.id, IdentityKey(Provider.GOOGLE, "s1"), reset_password=False
    )


def test_verified_email_takes_over_an_unverified_account_and_drops_its_password():
    # Whoever registered with a password never proved they own the address.
    squatter = _user("u1", "a@x.fi", verified=False, has_password=True)
    decision = decide_external_login(_claims(), by_identity=None, by_email=squatter)
    assert decision == LinkIdentity(
        squatter.id, IdentityKey(Provider.GOOGLE, "s1"), reset_password=True
    )


def test_unverified_email_never_links_and_is_not_stored_as_the_account_email():
    existing = _user("u1", "a@x.fi", verified=True)
    decision = decide_external_login(_claims(verified=False), by_identity=None, by_email=existing)
    assert isinstance(decision, CreateUser)
    assert decision.email is None
    assert decision.email_verified is False


def test_login_without_any_email_creates_a_user_without_email():
    decision = decide_external_login(
        _claims(email=None, verified=False), by_identity=None, by_email=None
    )
    assert isinstance(decision, CreateUser)
    assert decision.email is None


@given(
    verified=st.booleans(),
    has_email=st.booleans(),
    other_verified=st.booleans(),
    other_has_password=st.booleans(),
    same_email=st.booleans(),
)
def test_policy_invariants(verified, has_email, other_verified, other_has_password, same_email):
    verified = verified and has_email
    claims = _claims(email="a@x.fi" if has_email else None, verified=verified)
    other = _user(
        "u9",
        "a@x.fi" if same_email else "z@x.fi",
        verified=other_verified,
        has_password=other_has_password,
    )
    decision = decide_external_login(claims, by_identity=None, by_email=other)
    if isinstance(decision, LinkIdentity):
        # Linking only ever happens on a provider-verified, identical email ...
        assert claims.email_verified and claims.email == other.email
        # ... and the password of an unproven account never survives it.
        assert decision.reset_password == (not other.email_verified and other.has_password)
    if isinstance(decision, CreateUser):
        # An unverified email is never trusted as the account email.
        assert decision.email_verified == claims.email_verified
        assert (decision.email is not None) == claims.email_verified
