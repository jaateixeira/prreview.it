from datetime import UTC, datetime, timedelta

import pytest

from previewit.domain.identity import UserId
from previewit.domain.tenancy import (
    CREATOR_ROLES,
    DEFAULT_ROLES,
    EDUCATION,
    InvalidName,
    InvalidRole,
    Invite,
    OrgRole,
    Permission,
    Role,
    can_grant,
    clean_name,
    coerce_roles,
    format_roles,
    get_preset,
    parse_roles,
    permissions,
)

T0 = datetime(2026, 11, 12, 12, 0, tzinfo=UTC)
P = Permission


def test_education_preset_renames_the_fixed_roles():
    assert get_preset("education") is EDUCATION
    assert EDUCATION.word("organizer") == "teacher"
    assert EDUCATION.word("author") == "author" and EDUCATION.word("reviewer") == "reviewer"
    assert EDUCATION.word("space") == "course"
    assert EDUCATION.word("unknown-key") == "unknown-key"  # neutral fallback
    assert get_preset("nope") is None


def test_there_are_three_fixed_roles():
    assert {r.value for r in Role} == {"organizer", "author", "reviewer"}
    assert {Role.ORGANIZER} == CREATOR_ROLES
    assert {Role.AUTHOR, Role.REVIEWER} == DEFAULT_ROLES


# --- who may do what: the role x permission matrix ------------------------------------

ORG, A, R = Role.ORGANIZER, Role.AUTHOR, Role.REVIEWER

MATRIX = [
    # org role, space roles, expected permissions
    (OrgRole.OWNER, frozenset(), set(Permission)),
    (OrgRole.OWNER, {A}, set(Permission)),
    (OrgRole.MEMBER, {ORG}, set(Permission)),
    (OrgRole.MEMBER, {A}, {P.SPACE_VIEW, P.SUBMIT}),
    (OrgRole.MEMBER, {R}, {P.SPACE_VIEW}),
    (OrgRole.MEMBER, {A, R}, {P.SPACE_VIEW, P.SUBMIT}),
    (OrgRole.MEMBER, {R, ORG}, set(Permission)),  # a member may hold several roles
    (OrgRole.MEMBER, frozenset(), set()),
    (None, frozenset(), set()),
    (None, {A}, {P.SPACE_VIEW, P.SUBMIT}),
]


@pytest.mark.parametrize(("org_role", "roles", "expected"), MATRIX)
def test_permission_matrix(org_role, roles, expected):
    assert permissions(org_role, frozenset(roles)) == expected


def test_only_organizers_and_owners_manage_members_calls_rounds_or_the_space():
    for roles in ({A}, {R}, {A, R}):
        granted = permissions(OrgRole.MEMBER, frozenset(roles))
        for needed in (
            P.MEMBERS_MANAGE,
            P.SPACE_MANAGE,
            P.CALLS_MANAGE,
            P.ROUNDS_MANAGE,
            P.RUBRICS_MANAGE,
            P.SUBMISSIONS_VIEW_ALL,
        ):
            assert needed not in granted


def test_cannot_grant_a_role_stronger_than_your_own():
    participant = permissions(OrgRole.MEMBER, frozenset({A, R}))
    assert can_grant(participant, frozenset({A}))
    assert can_grant(participant, frozenset({A, R}))
    assert not can_grant(participant, frozenset({ORG}))
    assert not can_grant(participant, frozenset())  # a member always holds a role
    owner = permissions(OrgRole.OWNER, frozenset())
    assert can_grant(owner, frozenset(Role))


def test_roles_round_trip_through_their_stored_form():
    assert format_roles(frozenset({R, A})) == "author,reviewer"
    assert parse_roles("author,reviewer") == frozenset({A, R})
    assert parse_roles(format_roles(frozenset(Role))) == frozenset(Role)


@pytest.mark.parametrize("bad", ["", "emperor", "author,emperor", " , "])
def test_unknown_or_empty_roles_are_rejected(bad: str):
    with pytest.raises(InvalidRole):
        parse_roles(bad)


def test_coerce_accepts_roles_or_their_names_and_rejects_the_rest():
    assert coerce_roles(["author", Role.REVIEWER]) == frozenset({A, R})
    with pytest.raises(InvalidRole):
        coerce_roles([])
    with pytest.raises(InvalidRole):
        coerce_roles(["teacher"])  # a preset word, not a role


# --- names -------------------------------------------------------------------------------


def test_names_are_trimmed_and_bounded():
    assert clean_name("  Software Engineering 101 ") == "Software Engineering 101"
    for bad in ("", "   ", "x" * 101):
        with pytest.raises(InvalidName):
            clean_name(bad)


# --- invites -------------------------------------------------------------------------------


def _invite(**kw):
    base = dict(
        id="h",
        org_id="o1",
        space_id="s1",
        roles=frozenset({Role.AUTHOR, Role.REVIEWER}),
        created_by=UserId("u1"),
        expires_at=T0 + timedelta(days=7),
        max_uses=None,
        uses=0,
        revoked=False,
    )
    return Invite(**{**base, **kw})


def test_invite_usable_rules():
    assert _invite().usable(T0)
    assert not _invite().usable(T0 + timedelta(days=7))  # expired
    assert not _invite(revoked=True).usable(T0)
    assert _invite(max_uses=2, uses=1).usable(T0)
    assert not _invite(max_uses=2, uses=2).usable(T0)
