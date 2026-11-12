from datetime import UTC, datetime, timedelta

import pytest

from previewit.domain.identity import UserId
from previewit.domain.tenancy import (
    EDUCATION,
    InvalidName,
    Invite,
    OrgRole,
    Permission,
    can_grant,
    clean_name,
    get_preset,
    permissions,
)

T0 = datetime(2026, 11, 12, 12, 0, tzinfo=UTC)
P = Permission


def test_education_preset_roles_and_vocabulary():
    assert get_preset("education") is EDUCATION
    assert {r.key for r in EDUCATION.roles} == {"teacher", "assistant", "student"}
    assert EDUCATION.role(EDUCATION.creator_role) is not None
    assert EDUCATION.role(EDUCATION.default_role) is not None
    assert EDUCATION.word("space") == "course"
    assert EDUCATION.word("unknown-key") == "unknown-key"  # neutral fallback
    assert get_preset("nope") is None


# --- who may do what: the role x permission matrix ------------------------------------

MATRIX = [
    # org role, space role, expected permissions
    (OrgRole.OWNER, None, set(Permission)),
    (OrgRole.OWNER, "student", set(Permission)),
    (OrgRole.MEMBER, "teacher", set(Permission)),
    (
        OrgRole.MEMBER,
        "assistant",
        {P.SPACE_VIEW, P.MEMBERS_INVITE, P.GROUPS_MANAGE, P.SUBMIT, P.SUBMISSIONS_VIEW_ALL},
    ),
    (OrgRole.MEMBER, "student", {P.SPACE_VIEW, P.SUBMIT}),
    (OrgRole.MEMBER, None, set()),
    (None, None, set()),
    (None, "student", {P.SPACE_VIEW, P.SUBMIT}),
    (OrgRole.MEMBER, "role-that-does-not-exist", set()),
]


@pytest.mark.parametrize(("org_role", "space_role", "expected"), MATRIX)
def test_permission_matrix(org_role, space_role, expected):
    assert permissions(EDUCATION, org_role, space_role) == expected


def test_nobody_but_teachers_and_owners_manage_members_or_the_space():
    for role in ("assistant", "student"):
        granted = permissions(EDUCATION, OrgRole.MEMBER, role)
        assert P.MEMBERS_MANAGE not in granted and P.SPACE_MANAGE not in granted


def test_cannot_grant_a_role_stronger_than_your_own():
    assistant = permissions(EDUCATION, OrgRole.MEMBER, "assistant")
    assert can_grant(EDUCATION, assistant, "student")
    assert can_grant(EDUCATION, assistant, "assistant")
    assert not can_grant(EDUCATION, assistant, "teacher")
    assert not can_grant(EDUCATION, assistant, "unknown")
    owner = permissions(EDUCATION, OrgRole.OWNER, None)
    assert all(can_grant(EDUCATION, owner, r.key) for r in EDUCATION.roles)


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
        role_key="student",
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
