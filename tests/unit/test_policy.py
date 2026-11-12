import pytest

from previewit.domain.identity import Email, User, UserId
from previewit.domain.policy import DEFAULT_POLICY, Action, VerificationPolicy, parse_actions


def _user(*, verified: bool, email: bool = True) -> User:
    return User(UserId("u"), "A", Email("a@x.fi") if email else None, verified, frozenset(), False)


def test_default_only_review_needs_a_verified_email():
    # decided: unverified users may be invited, join and submit, but cannot review
    assert DEFAULT_POLICY.required_for == {Action.REVIEW}
    unverified = _user(verified=False)
    assert DEFAULT_POLICY.allows(unverified, Action.JOIN)
    assert DEFAULT_POLICY.allows(unverified, Action.SUBMIT)
    assert not DEFAULT_POLICY.allows(unverified, Action.REVIEW)
    assert DEFAULT_POLICY.allows(_user(verified=True), Action.REVIEW)


def test_a_user_without_an_email_counts_as_unverified():
    assert not DEFAULT_POLICY.allows(_user(verified=False, email=False), Action.REVIEW)
    assert DEFAULT_POLICY.allows(_user(verified=False, email=False), Action.SUBMIT)


def test_policies_can_require_more_or_nothing():
    strict = VerificationPolicy(frozenset(Action))
    lax = VerificationPolicy(frozenset())
    unverified = _user(verified=False)
    assert not any(strict.allows(unverified, a) for a in Action)
    assert all(lax.allows(unverified, a) for a in Action)


def test_parse_actions():
    assert parse_actions(["review", "submit"]) == {Action.REVIEW, Action.SUBMIT}
    assert parse_actions([]) == frozenset()
    with pytest.raises(ValueError, match="reveiw"):
        parse_actions(["reveiw"])  # a typo must not silently weaken the policy
