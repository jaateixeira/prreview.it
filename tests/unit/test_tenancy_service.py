from datetime import UTC, datetime, timedelta
from itertools import count

import pytest

from previewit.adapters.persistence.memory import (
    InMemoryTenancyRepository,
    InMemoryUserRepository,
)
from previewit.application.tenancy import (
    Forbidden,
    InvalidInvite,
    NotAMember,
    NotFound,
    TenancyService,
    VerificationRequired,
)
from previewit.domain.identity import Email, User, UserId
from previewit.domain.policy import Action, VerificationPolicy
from previewit.domain.tenancy import DEFAULT_ROLES, InvalidName, OrgRole, Role

T0 = datetime(2026, 11, 12, 12, 0, tzinfo=UTC)

ALICE, TINA, AVA, SAM, BOB, ZED = (UserId(n) for n in ("alice", "tina", "ava", "sam", "bob", "zed"))


class Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now


class World:
    """Org A (owner alice) with course S (organizer tina, reviewer ava, author+reviewer sam).
    Org B (owner bob) with course T. zed is a user with no memberships."""

    def __init__(self, users=None, repo=None) -> None:
        users = users or InMemoryUserRepository()
        for uid in (ALICE, TINA, AVA, SAM, BOB, ZED):
            users.add_user(
                User(uid, uid.title(), Email(f"{uid}@x.fi"), False, frozenset(), False), None
            )
        self.clock = Clock()
        ids = count(1)
        self.t = TenancyService(
            repo or InMemoryTenancyRepository(), users, lambda: f"id{next(ids)}", self.clock
        )
        self.org_a = self.t.create_organization(ALICE, "School A", "education")
        self.org_b = self.t.create_organization(BOB, "School B", "education")
        self.s = self.t.create_space(ALICE, self.org_a.id, "Software Engineering")
        self.other = self.t.create_space(BOB, self.org_b.id, "Databases")
        # staff join through invite links, as real users would
        for user, roles in (
            (TINA, ["organizer"]),
            (AVA, ["reviewer"]),
            (SAM, ["author", "reviewer"]),
        ):
            _, token = self.t.create_invite(ALICE, self.s.id, roles=roles)
            self.t.accept_invite(user, token)


@pytest.fixture
def w() -> World:
    return World()


# --- organizations and spaces ---------------------------------------------------------------


def test_creating_an_organization_makes_you_its_owner(w: World):
    assert [(o.name, r) for o, r in w.t.my_organizations(ALICE)] == [("School A", OrgRole.OWNER)]


def test_unknown_preset_is_rejected(w: World):
    with pytest.raises(ValueError):
        w.t.create_organization(ZED, "X", "no-such-preset")


def test_names_are_validated(w: World):
    with pytest.raises(InvalidName):
        w.t.create_organization(ZED, "  ", "education")
    with pytest.raises(InvalidName):
        w.t.create_space(ALICE, w.org_a.id, "")


def test_only_owners_create_spaces(w: World):
    with pytest.raises(Forbidden):
        w.t.create_space(TINA, w.org_a.id, "Sneaky")  # a member of org A, not an owner
    with pytest.raises(NotFound):
        w.t.create_space(ZED, w.org_a.id, "Sneaky")  # not even a member


def test_space_creator_becomes_organizer_and_lists_show_only_what_you_may_see(w: World):
    names = lambda spaces: [s.name for s, _ in spaces]  # noqa: E731
    assert names(w.t.my_spaces(ALICE)) == ["Software Engineering"]  # owner sees all in own org
    assert names(w.t.my_spaces(SAM)) == ["Software Engineering"]
    assert names(w.t.my_spaces(ZED)) == []
    assert names(w.t.my_spaces(BOB)) == ["Databases"]
    members = {m.user_id: m.roles for m in w.t.members(ALICE, w.s.id)}
    assert members[ALICE] == frozenset({Role.ORGANIZER})


# --- tenant isolation: every operation, from every kind of outsider ---------------------------


def _operations(w: World):
    g = w.t.create_group(ALICE, w.s.id, "Group 1")
    return {
        "view": lambda u: w.t.space_view(u, w.s.id),
        "members": lambda u: w.t.members(u, w.s.id),
        "invites": lambda u: w.t.invites(u, w.s.id),
        "create_invite": lambda u: w.t.create_invite(u, w.s.id),
        "change_roles": lambda u: w.t.change_roles(u, w.s.id, SAM, ["reviewer"]),
        "remove": lambda u: w.t.remove_member(u, w.s.id, SAM),
        "groups": lambda u: w.t.groups(u, w.s.id),
        "create_group": lambda u: w.t.create_group(u, w.s.id, "x"),
        "rename_group": lambda u: w.t.rename_group(u, w.s.id, g.id, "x"),
        "delete_group": lambda u: w.t.delete_group(u, w.s.id, g.id),
        "group_add": lambda u: w.t.add_to_group(u, w.s.id, g.id, SAM),
        "org_spaces": lambda u: w.t.org_spaces(u, w.org_a.id),
    }


@pytest.mark.parametrize("outsider", [BOB, ZED], ids=["other-tenant-owner", "no-memberships"])
def test_outsiders_cannot_even_tell_the_space_exists(w: World, outsider: UserId):
    for name, op in _operations(w).items():
        with pytest.raises(NotFound):
            op(outsider)
        # and nothing changed
        assert [m.user_id for m in w.t.members(ALICE, w.s.id)].count(SAM) == 1, name


def test_a_member_of_another_space_in_the_same_org_is_an_outsider_to_this_one(w: World):
    other = w.t.create_space(ALICE, w.org_a.id, "Algorithms")
    _, token = w.t.create_invite(ALICE, other.id, roles=["organizer"])
    w.t.accept_invite(ZED, token)  # zed organizes Algorithms only
    with pytest.raises(NotFound):
        w.t.members(ZED, w.s.id)
    assert [s.name for s in w.t.org_spaces(ZED, w.org_a.id)] == ["Algorithms"]


# --- the authorisation matrix inside a space ---------------------------------------------------

#            op                 organizer reviewer participant (author + reviewer)
EXPECT = {
    "view": (True, True, True),
    "members": (True, True, True),
    "invites": (True, False, False),
    "create_invite": (True, False, False),
    "change_roles": (True, False, False),
    "remove": (True, False, False),
    "groups": (True, True, True),
    "create_group": (True, False, False),
    "rename_group": (True, False, False),
    "delete_group": (True, False, False),
    "group_add": (True, False, False),
}


@pytest.mark.parametrize("op_name", list(EXPECT))
@pytest.mark.parametrize(
    "who", [(TINA, 0), (AVA, 1), (SAM, 2)], ids=["organizer", "reviewer", "participant"]
)
def test_authorisation_matrix(w: World, op_name: str, who: tuple[UserId, int]):
    user, index = who
    op = _operations(w)[op_name]
    if EXPECT[op_name][index]:
        op(user)
    else:
        with pytest.raises(Forbidden):
            op(user)


# --- invites -----------------------------------------------------------------------------------


def test_joining_by_link_adds_you_to_the_org_and_the_space(w: World):
    _, token = w.t.create_invite(TINA, w.s.id)
    space = w.t.accept_invite(ZED, token)
    assert space.id == w.s.id
    assert w.t.space_view(ZED, w.s.id).roles == DEFAULT_ROLES
    assert (w.org_a.name, OrgRole.MEMBER) in [(o.name, r) for o, r in w.t.my_organizations(ZED)]


def test_unverified_users_can_join(w: World):
    _, token = w.t.create_invite(TINA, w.s.id)
    w.t.accept_invite(ZED, token)  # zed's email is unverified (see World)


def test_the_secret_is_not_stored_and_cannot_be_guessed_from_the_id(w: World):
    invite, token = w.t.create_invite(TINA, w.s.id)
    assert token not in (invite.id, invite.space_id) and len(token) >= 40


def test_only_organizers_mint_invites_of_any_role(w: World):
    for who in (AVA, SAM):
        with pytest.raises(Forbidden):
            w.t.create_invite(who, w.s.id, roles=["author"])
    w.t.create_invite(TINA, w.s.id, roles=["organizer"])


def test_unknown_role_in_an_invite_is_rejected(w: World):
    with pytest.raises(Forbidden):
        w.t.create_invite(TINA, w.s.id, roles=["emperor"])
    with pytest.raises(Forbidden):
        w.t.create_invite(TINA, w.s.id, roles=[])


@pytest.mark.parametrize("token", ["", "garbage", "x" * 43])
def test_bad_tokens(w: World, token: str):
    with pytest.raises(InvalidInvite):
        w.t.accept_invite(ZED, token)


def test_expiry_max_uses_and_revocation(w: World):
    _, expiring = w.t.create_invite(TINA, w.s.id, ttl=timedelta(days=1))
    w.clock.now = T0 + timedelta(days=1, seconds=1)
    with pytest.raises(InvalidInvite):
        w.t.accept_invite(ZED, expiring)

    w.clock.now = T0
    _, single = w.t.create_invite(TINA, w.s.id, max_uses=1)
    w.t.accept_invite(ZED, single)
    with pytest.raises(InvalidInvite):
        w.t.accept_invite(BOB, single)

    invite, revoked = w.t.create_invite(TINA, w.s.id)
    w.t.revoke_invite(TINA, w.s.id, invite.id)
    with pytest.raises(InvalidInvite):
        w.t.accept_invite(BOB, revoked)


def test_a_member_following_a_link_again_changes_nothing_and_uses_no_seat(w: World):
    invite, token = w.t.create_invite(TINA, w.s.id, roles=["author"], max_uses=1)
    w.t.accept_invite(SAM, token)  # already a member: nothing consumed
    assert next(i for i in w.t.invites(TINA, w.s.id) if i.id == invite.id).uses == 0
    # and an author link never demotes an organizer
    w.t.accept_invite(TINA, token)
    assert w.t.space_view(TINA, w.s.id).roles == frozenset({Role.ORGANIZER})
    assert invite.max_uses == 1


def test_preview_of_a_link_shows_the_space_but_not_for_dead_links(w: World):
    _, token = w.t.create_invite(TINA, w.s.id)
    preview = w.t.preview_invite(token)
    assert preview is not None and preview.space_name == "Software Engineering"
    assert preview.organization_name == "School A" and preview.role_label == "Author, reviewer"
    assert w.t.preview_invite("nope") is None


def test_an_invite_cannot_be_revoked_through_another_space(w: World):
    other = w.t.create_space(ALICE, w.org_a.id, "Algorithms")
    invite, token = w.t.create_invite(ALICE, other.id)
    with pytest.raises(NotFound):
        w.t.revoke_invite(TINA, w.s.id, invite.id)  # tina teaches S, not Algorithms
    w.t.accept_invite(ZED, token)  # still valid


# --- members -----------------------------------------------------------------------------------


def test_member_lists_show_emails_only_to_managers(w: World):
    as_participant = {m.user_id: m for m in w.t.members(SAM, w.s.id)}
    as_organizer = {m.user_id: m for m in w.t.members(TINA, w.s.id)}
    assert as_participant[AVA].display_name == "Ava" and as_participant[AVA].email is None
    assert as_organizer[SAM].email == "sam@x.fi"


def test_role_changes_respect_escalation_and_lockout_rules(w: World):
    w.t.change_roles(TINA, w.s.id, SAM, ["reviewer"])
    assert w.t.space_view(SAM, w.s.id).roles == frozenset({Role.REVIEWER})
    w.t.change_roles(TINA, w.s.id, SAM, ["author", "reviewer", "organizer"])
    assert w.t.space_view(SAM, w.s.id).roles == frozenset(Role)
    with pytest.raises(Forbidden):
        w.t.change_roles(TINA, w.s.id, TINA, ["author"])  # no self-demotion
    w.t.change_roles(TINA, w.s.id, TINA, ["organizer", "reviewer"])  # adding a role to yourself
    assert w.t.space_view(TINA, w.s.id).roles == frozenset({Role.ORGANIZER, Role.REVIEWER})
    with pytest.raises(Forbidden):
        w.t.change_roles(TINA, w.s.id, SAM, ["emperor"])
    with pytest.raises(Forbidden):
        w.t.change_roles(TINA, w.s.id, SAM, [])  # a member holds at least one role
    with pytest.raises(NotAMember):
        w.t.change_roles(TINA, w.s.id, ZED, ["author"])


def test_removing_a_member_also_removes_them_from_groups(w: World):
    g = w.t.create_group(TINA, w.s.id, "G", members=[SAM])
    w.t.remove_member(TINA, w.s.id, SAM)
    assert w.t.groups(TINA, w.s.id)[0].members == frozenset()
    assert g.members == frozenset({SAM})
    with pytest.raises(NotFound):
        w.t.space_view(SAM, w.s.id)
    with pytest.raises(Forbidden):
        w.t.remove_member(TINA, w.s.id, TINA)


def test_organizers_cannot_be_removed_by_lesser_roles(w: World):
    with pytest.raises(Forbidden):
        w.t.remove_member(AVA, w.s.id, TINA)


# --- groups ------------------------------------------------------------------------------------


def test_group_lifecycle(w: World):
    g = w.t.create_group(TINA, w.s.id, " Team  Red ", members=[SAM])
    assert g.name == "Team Red" and g.members == frozenset({SAM})
    w.t.rename_group(TINA, w.s.id, g.id, "Team Blue")
    w.t.add_to_group(TINA, w.s.id, g.id, TINA)
    w.t.remove_from_group(TINA, w.s.id, g.id, SAM)
    (group,) = w.t.groups(SAM, w.s.id)
    assert (group.name, group.members) == ("Team Blue", frozenset({TINA}))
    w.t.delete_group(TINA, w.s.id, g.id)
    assert w.t.groups(SAM, w.s.id) == []


def test_only_space_members_can_join_groups(w: World):
    with pytest.raises(NotAMember):
        w.t.create_group(TINA, w.s.id, "G", members=[ZED])
    g = w.t.create_group(TINA, w.s.id, "G")
    with pytest.raises(NotAMember):
        w.t.add_to_group(TINA, w.s.id, g.id, BOB)


def test_a_group_id_from_another_space_is_not_found(w: World):
    other = w.t.create_space(ALICE, w.org_a.id, "Algorithms")
    foreign = w.t.create_group(ALICE, other.id, "Elsewhere")
    with pytest.raises(NotFound):
        w.t.rename_group(TINA, w.s.id, foreign.id, "hijacked")
    with pytest.raises(NotFound):
        w.t.delete_group(TINA, w.s.id, foreign.id)
    assert w.t.groups(ALICE, other.id)[0].name == "Elsewhere"


# --- the email-verification policy -------------------------------------------------------


def _policy_service(required: frozenset[Action]):
    users = InMemoryUserRepository()
    for uid, verified in (("ver", True), ("unver", False)):
        users.add_user(
            User(UserId(uid), uid, Email(f"{uid}@x.fi"), verified, frozenset(), False), None
        )
    ids = count(1)
    svc = TenancyService(
        InMemoryTenancyRepository(),
        users,
        lambda: f"id{next(ids)}",
        Clock(),
        policy=VerificationPolicy(required),
    )
    return svc, UserId("ver"), UserId("unver")


def test_default_policy_lets_unverified_users_create_invite_and_join():
    default = TenancyService(InMemoryTenancyRepository(), InMemoryUserRepository(), str, Clock())
    assert default is not None  # constructing without a policy must keep working
    svc, ver, unver = _policy_service(frozenset())
    org = svc.create_organization(unver, "Org", "education")
    space = svc.create_space(unver, org.id, "Course")
    _, token = svc.create_invite(unver, space.id)
    assert svc.accept_invite(ver, token).id == space.id


def test_create_organization_can_require_a_verified_email():
    svc, ver, unver = _policy_service(frozenset({Action.CREATE_ORGANIZATION}))
    with pytest.raises(VerificationRequired) as e:
        svc.create_organization(unver, "Org", "education")
    assert e.value.action is Action.CREATE_ORGANIZATION
    assert svc.my_organizations(unver) == []  # nothing was created
    assert svc.create_organization(ver, "Org", "education").name == "Org"


def test_inviting_can_require_a_verified_email():
    svc, ver, _unver = _policy_service(frozenset({Action.INVITE}))
    org = svc.create_organization(ver, "Org", "education")
    space = svc.create_space(ver, org.id, "Course")
    invite, _token = svc.create_invite(ver, space.id)  # verified owner may
    assert invite.space_id == space.id
    strict, _ver2, unver2 = _policy_service(frozenset({Action.INVITE}))
    org2 = strict.create_organization(unver2, "Org", "education")
    space2 = strict.create_space(unver2, org2.id, "Course")
    with pytest.raises(VerificationRequired):
        strict.create_invite(unver2, space2.id)
    assert strict.invites(unver2, space2.id) == []


def test_joining_can_require_a_verified_email_and_keeps_the_link_unused():
    svc, ver, unver = _policy_service(frozenset({Action.JOIN}))
    org = svc.create_organization(ver, "Org", "education")
    space = svc.create_space(ver, org.id, "Course")
    invite, token = svc.create_invite(ver, space.id, max_uses=1)
    with pytest.raises(VerificationRequired):
        svc.accept_invite(unver, token)
    assert svc.invites(ver, space.id)[0].uses == 0  # a refused attempt does not burn the link
    assert svc.accept_invite(ver, token).id == space.id
    assert invite.max_uses == 1


def test_a_bad_link_is_reported_as_invalid_before_the_verification_requirement():
    svc, _ver, unver = _policy_service(frozenset({Action.JOIN}))
    with pytest.raises(InvalidInvite):
        svc.accept_invite(unver, "garbage")
