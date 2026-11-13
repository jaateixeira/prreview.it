from datetime import timedelta
from itertools import count

import pytest

from previewit.adapters.entitlements import UnlimitedEntitlements
from previewit.adapters.persistence.memory import InMemoryUserRepository
from previewit.adapters.persistence.memory_calls import InMemoryCallRepository
from previewit.application.artifacts import (
    ArtifactError,
    ArtifactRegistry,
    UnknownArtifactType,
    Upload,
)
from previewit.application.calls import (
    AlreadySubmitted,
    CallClosed,
    CallHasSubmissions,
    CallsService,
    InvalidShare,
    ShareLimitReached,
)
from previewit.application.tenancy import Forbidden, NotFound, VerificationRequired
from previewit.domain.calls import CallAccess, CallId, InvalidCall, ShareTarget
from previewit.domain.identity import Email, User, UserId
from previewit.domain.policy import Action, VerificationPolicy
from previewit.domain.tenancy import Role
from previewit.plugins.pdf import PdfArtifact
from previewit.plugins.text import TextArtifact
from tests.unit import test_tenancy_service as base
from tests.unit.test_tenancy_service import ALICE, AVA, BOB, SAM, T0, TINA, ZED

SUE, PAT = UserId("sue"), UserId("pat")
PDF = b"%PDF-1.7\n%%EOF\n"


class NoShares:
    def may_create_share(self, user_id: UserId, shares_so_far: int) -> bool:
        return False


class CWorld(base.World):
    """The tenancy world plus two more students (sue, pat) and a calls service."""

    def __init__(self, users=None, repo=None, calls_repo=None, *, policy=None, entitlements=None):
        users = users or InMemoryUserRepository()
        super().__init__(users=users, repo=repo)
        repo = repo or self.t._repo
        for uid in (SUE, PAT):
            users.add_user(
                User(uid, uid.title(), Email(f"{uid}@x.fi"), False, frozenset(), False), None
            )
            _, token = self.t.create_invite(ALICE, self.s.id, roles=["author", "reviewer"])
            self.t.accept_invite(uid, token)
        ids = count(1)
        kw = {"policy": policy} if policy else {}
        self.users = users
        self.c = CallsService(
            calls_repo or InMemoryCallRepository(),
            self.t,
            repo,
            users,
            ArtifactRegistry([TextArtifact(), PdfArtifact()]),
            entitlements or UnlimitedEntitlements(),
            lambda: f"c{next(ids)}",
            self.clock,
            **kw,
        )
        self.call = self.c.create_call(
            TINA, self.s.id, title="Essay 1", artifact_type="text", published=True
        )

    def essay(self, user=SAM, title="My essay", text="Hello", **kw):
        return self.c.submit(user, self.call.id, title=title, upload=Upload(text=text), **kw)

    def group_call(self):
        call = self.c.create_call(
            TINA, self.s.id, title="Project", artifact_type="text", group_work=True, published=True
        )
        group = self.t.create_group(TINA, self.s.id, "Group 1")
        for member in (SAM, SUE):
            self.t.add_to_group(TINA, self.s.id, group.id, member)
        return call, group


@pytest.fixture
def w() -> CWorld:
    return CWorld()


# --- call management -----------------------------------------------------------------------------


def test_only_staff_with_the_permission_manage_calls(w: CWorld):
    for user in (SAM, AVA):  # author+reviewer, reviewer
        with pytest.raises(Forbidden):
            w.c.create_call(user, w.s.id, title="X", artifact_type="text")
    with pytest.raises(NotFound):
        w.c.create_call(BOB, w.s.id, title="X", artifact_type="text")  # another tenant
    assert w.c.create_call(ALICE, w.s.id, title="X", artifact_type="pdf").artifact_type == "pdf"


def test_a_call_needs_a_valid_title_and_an_installed_artifact_type(w: CWorld):
    with pytest.raises(InvalidCall):
        w.c.create_call(TINA, w.s.id, title="  ", artifact_type="text")
    with pytest.raises(UnknownArtifactType):
        w.c.create_call(TINA, w.s.id, title="X", artifact_type="code")


def test_students_see_only_published_calls(w: CWorld):
    draft = w.c.create_call(TINA, w.s.id, title="Draft", artifact_type="text")
    assert {c.title for c in w.c.calls(TINA, w.s.id)} == {"Essay 1", "Draft"}
    assert {c.title for c in w.c.calls(SAM, w.s.id)} == {"Essay 1"}
    with pytest.raises(NotFound):
        w.c.call_view(SAM, draft.id)
    assert w.c.call_view(TINA, draft.id).call.title == "Draft"


def test_update_and_delete(w: CWorld):
    updated = w.c.update_call(
        TINA, w.call.id, title="Essay one", description="d", closes_at=None, published=False
    )
    assert (updated.title, updated.published, updated.artifact_type) == ("Essay one", False, "text")
    with pytest.raises(Forbidden):
        w.c.update_call(SAM, w.call.id, title="x", description="", closes_at=None, published=True)
    w.c.update_call(TINA, w.call.id, title="E", description="", closes_at=None, published=True)
    w.essay()
    with pytest.raises(CallHasSubmissions):
        w.c.delete_call(TINA, w.call.id)
    other = w.c.create_call(TINA, w.s.id, title="Temp", artifact_type="text")
    w.c.delete_call(TINA, other.id)
    with pytest.raises(NotFound):
        w.c.call_view(TINA, other.id)


# --- individual submissions and revisions -------------------------------------------------------


def test_a_student_submits_then_adds_revisions_and_old_ones_never_change(w: CWorld):
    sub = w.essay(text="first draft")
    with pytest.raises(AlreadySubmitted):
        w.essay(text="again")
    r2 = w.c.revise(SAM, sub.id, Upload(text="second draft"))
    assert r2.number == 2
    view = w.c.submission_view(SAM, sub.id)
    assert [r.number for r in view.revisions] == [1, 2]
    assert view.latest.artifact.content == b"second draft" and view.can_revise
    assert w.c.revision(SAM, sub.id, 1).artifact.content == b"first draft"
    with pytest.raises(NotFound):
        w.c.revision(SAM, sub.id, 3)


def test_the_artifact_plugin_decides_what_is_acceptable(w: CWorld):
    with pytest.raises(ArtifactError):
        w.essay(text="   ")
    pdf_call = w.c.create_call(TINA, w.s.id, title="Paper", artifact_type="pdf", published=True)
    with pytest.raises(ArtifactError):
        w.c.submit(SAM, pdf_call.id, title="Paper", upload=Upload(text="not a file"))
    sub = w.c.submit(SAM, pdf_call.id, title="Paper", upload=Upload(content=PDF, filename="a.pdf"))
    view = w.c.submission_view(SAM, sub.id)
    assert view.latest.artifact.media_type == "application/pdf"
    assert view.artifact_type.key == "pdf"


def test_a_failed_upload_leaves_no_submission_behind(w: CWorld):
    with pytest.raises(ArtifactError):
        w.essay(text="")
    assert w.c.call_view(SAM, w.call.id).mine == []
    assert w.essay().id  # and the student can still submit


def test_peers_cannot_see_each_others_work_but_staff_can(w: CWorld):
    sub = w.essay(SAM)
    for peer in (SUE, PAT):
        with pytest.raises(NotFound):
            w.c.submission_view(peer, sub.id)
        with pytest.raises(NotFound):
            w.c.revision(peer, sub.id, 1)
    with pytest.raises(NotFound):
        w.c.submission_view(BOB, sub.id)  # another tenant
    with pytest.raises(NotFound):
        w.c.submission_view(ZED, sub.id)
    for staff in (TINA, ALICE):
        assert w.c.submission_view(staff, sub.id).author_name == "Sam"
    with pytest.raises(Forbidden):
        w.c.revise(TINA, sub.id, Upload(text="I edit your work"))  # staff cannot edit it


def test_call_view_lists_everything_only_for_staff(w: CWorld):
    w.essay(SAM, "S")
    w.essay(SUE, "U")
    assert [s.submission.title for s in w.c.call_view(SAM, w.call.id).mine] == ["S"]
    assert w.c.call_view(SAM, w.call.id).everyone is None
    everyone = w.c.call_view(TINA, w.call.id).everyone
    assert everyone is not None and {s.author_name for s in everyone} == {"Sam", "Sue"}


def test_the_deadline_closes_submissions_and_revisions(w: CWorld):
    closing = w.c.create_call(
        TINA, w.s.id, title="Soon", artifact_type="text", published=True,
        closes_at=T0 + timedelta(days=1),
    )  # fmt: skip
    sub = w.c.submit(SAM, closing.id, title="S", upload=Upload(text="a"))
    w.clock.now = T0 + timedelta(days=1)
    with pytest.raises(CallClosed):
        w.c.revise(SAM, sub.id, Upload(text="b"))
    with pytest.raises(CallClosed):
        w.c.submit(SUE, closing.id, title="S", upload=Upload(text="a"))
    view = w.c.submission_view(SAM, sub.id)
    assert not view.can_revise and view.latest.artifact.content == b"a"  # still readable


# --- group submissions ---------------------------------------------------------------------------


def test_a_group_submits_once_and_every_member_can_revise(w: CWorld):
    call, group = w.group_call()
    sub = w.c.submit(SAM, call.id, title="Our project", upload=Upload(text="v1"))
    assert sub.author.group_id == group.id  # type: ignore[union-attr]
    with pytest.raises(AlreadySubmitted):
        w.c.submit(SUE, call.id, title="Again", upload=Upload(text="x"))
    assert w.c.revise(SUE, sub.id, Upload(text="v2")).number == 2
    assert w.c.submission_view(SUE, sub.id).author_name == "Group 1"
    assert w.c.call_view(SUE, call.id).mine[0].submission.id == sub.id
    with pytest.raises(NotFound):
        w.c.submission_view(PAT, sub.id)  # not in the group


def test_you_cannot_submit_for_a_group_you_are_not_in(w: CWorld):
    call, group = w.group_call()
    with pytest.raises(Forbidden):
        w.c.submit(PAT, call.id, title="x", upload=Upload(text="x"))  # in no group
    with pytest.raises(Forbidden):
        w.c.submit(PAT, call.id, title="x", upload=Upload(text="x"), group_id=group.id)


def test_leaving_the_group_ends_your_access_to_its_work(w: CWorld):
    call, group = w.group_call()
    sub = w.c.submit(SAM, call.id, title="P", upload=Upload(text="v1"))
    w.t.remove_from_group(TINA, w.s.id, group.id, SAM)
    with pytest.raises(NotFound):
        w.c.submission_view(SAM, sub.id)


# --- review by link ---------------------------------------------------------------


def test_a_call_link_admits_the_holder_as_an_author(w: CWorld):
    """A protected call: the link carries the token (ADR 0017). Opening it makes you an author."""
    assert w.call.access is CallAccess.PROTECTED  # protected unless the organizer opens it up
    _, token = w.c.create_share(TINA, ShareTarget.CALL, w.call.id)
    preview = w.c.preview_share(token)
    assert preview is not None and (preview.title, preview.shared_by) == ("Essay 1", "Tina")
    with pytest.raises(NotFound):
        w.c.call_view(ZED, w.call.id)  # no access before opening the link
    item = w.c.accept_share(ZED, token)
    assert (item.target, item.target_id) == (ShareTarget.CALL, w.call.id)
    assert w.t.space_view(ZED, w.s.id).roles == frozenset({Role.AUTHOR})
    view = w.c.call_view(ZED, w.call.id)
    assert not view.guest and view.can_submit and view.everyone is None
    assert w.essay(ZED).author.user_id == ZED  # type: ignore[union-attr]
    assert [i.title for i in w.c.shared_with_me(ZED)] == ["Essay 1"]


def test_revoking_a_call_link_stops_new_authors_but_keeps_those_who_joined(w: CWorld):
    link, token = w.c.create_share(TINA, ShareTarget.CALL, w.call.id)
    w.c.accept_share(ZED, token)
    w.c.revoke_share(TINA, ShareTarget.CALL, w.call.id, link.id)
    with pytest.raises(InvalidShare):
        w.c.accept_share(BOB, token)
    assert w.c.call_view(ZED, w.call.id).can_submit  # already in


def test_a_link_to_a_draft_call_admits_nobody(w: CWorld):
    draft = w.c.create_call(TINA, w.s.id, title="Draft", artifact_type="text")
    _, token = w.c.create_share(TINA, ShareTarget.CALL, draft.id)
    with pytest.raises(InvalidShare):
        w.c.accept_share(ZED, token)
    with pytest.raises(NotFound):
        w.t.space_view(ZED, w.s.id)


def test_following_a_call_link_never_demotes_a_member(w: CWorld):
    _, token = w.c.create_share(TINA, ShareTarget.CALL, w.call.id)
    w.c.accept_share(TINA, token)
    assert w.t.space_view(TINA, w.s.id).roles == frozenset({Role.ORGANIZER})


def test_a_public_call_needs_no_token(w: CWorld):
    public = w.c.create_call(
        TINA, w.s.id, title="Open", artifact_type="text", published=True, access=CallAccess.PUBLIC
    )
    preview = w.c.public_preview(public.id)
    assert preview is not None and preview.title == "Open"
    assert (preview.space_name, preview.organization_name) == ("Software Engineering", "School A")
    item = w.c.open_public(ZED, public.id)
    assert (item.target, item.target_id) == (ShareTarget.CALL, public.id)
    assert w.t.space_view(ZED, w.s.id).roles == frozenset({Role.AUTHOR})
    assert w.c.submit(ZED, public.id, title="Mine", upload=Upload(text="x")).title == "Mine"


def test_a_protected_or_draft_call_cannot_be_opened_by_its_plain_address(w: CWorld):
    draft = w.c.create_call(
        TINA, w.s.id, title="Draft", artifact_type="text", access=CallAccess.PUBLIC
    )
    for call_id in (w.call.id, draft.id, CallId("no-such-call")):  # protected, draft, missing
        assert w.c.public_preview(call_id) is None
        with pytest.raises(NotFound):
            w.c.open_public(ZED, call_id)
    with pytest.raises(NotFound):
        w.t.space_view(ZED, w.s.id)


def test_the_organizer_chooses_and_changes_the_access_mode(w: CWorld):
    assert (
        w.c.update_call(
            TINA,
            w.call.id,
            title="Essay 1",
            description="",
            closes_at=None,
            published=True,
            access=CallAccess.PUBLIC,
        ).access
        is CallAccess.PUBLIC
    )
    assert w.c.public_preview(w.call.id) is not None
    w.c.update_call(
        TINA, w.call.id, title="Essay 1", description="", closes_at=None, published=True
    )  # access left as it was
    assert w.c.public_preview(w.call.id) is not None
    with pytest.raises(Forbidden):
        w.c.update_call(
            SAM, w.call.id, title="x", description="", closes_at=None, published=True,
            access=CallAccess.PROTECTED,
        )  # fmt: skip


def test_a_shared_submission_shows_that_work_and_nothing_else(w: CWorld):
    mine, theirs = w.essay(SAM, "Mine", "m"), w.essay(SUE, "Theirs", "t")
    _, token = w.c.create_share(SAM, ShareTarget.SUBMISSION, mine.id)
    w.c.accept_share(ZED, token)
    view = w.c.submission_view(ZED, mine.id)
    assert view.guest and not view.can_revise and not view.can_share
    assert w.c.revision(ZED, mine.id, 1).artifact.content == b"m"
    with pytest.raises(NotFound):
        w.c.submission_view(ZED, theirs.id)
    with pytest.raises(Forbidden):
        w.c.revise(ZED, mine.id, Upload(text="hijack"))
    with pytest.raises(NotFound):
        w.c.call_view(ZED, w.call.id)  # a submission link does not open the call


def test_who_may_create_share_links(w: CWorld):
    sub = w.essay(SAM)
    with pytest.raises(Forbidden):
        w.c.create_share(SAM, ShareTarget.CALL, w.call.id)  # students cannot share calls
    with pytest.raises(NotFound):
        w.c.create_share(SUE, ShareTarget.SUBMISSION, sub.id)  # not your work
    with pytest.raises(NotFound):
        w.c.create_share(BOB, ShareTarget.CALL, "nope")
    link, _token = w.c.create_share(TINA, ShareTarget.SUBMISSION, sub.id)  # staff may
    assert link.target is ShareTarget.SUBMISSION


def test_expired_and_revoked_links_stop_working_but_grants_remain(w: CWorld):
    link, token = w.c.create_share(TINA, ShareTarget.CALL, w.call.id)
    assert w.c.accept_share(ZED, token)
    w.c.revoke_share(TINA, ShareTarget.CALL, w.call.id, link.id)
    assert w.c.preview_share(token) is None
    with pytest.raises(InvalidShare):
        w.c.accept_share(BOB, token)
    assert w.c.call_view(ZED, w.call.id).can_submit  # already an author: keeps access
    _, token2 = w.c.create_share(TINA, ShareTarget.CALL, w.call.id, ttl=timedelta(hours=1))
    w.clock.now = T0 + timedelta(hours=1)
    assert w.c.preview_share(token2) is None
    with pytest.raises(InvalidShare):
        w.c.accept_share(BOB, token2)
    with pytest.raises(InvalidShare):
        w.c.accept_share(BOB, "garbage")
    assert w.c.preview_share("") is None


def test_revoking_needs_the_right_target(w: CWorld):
    link, _ = w.c.create_share(TINA, ShareTarget.CALL, w.call.id)
    other = w.c.create_call(TINA, w.s.id, title="Other", artifact_type="text", published=True)
    with pytest.raises(NotFound):
        w.c.revoke_share(TINA, ShareTarget.CALL, other.id, link.id)
    with pytest.raises(Forbidden):
        w.c.revoke_share(SAM, ShareTarget.CALL, w.call.id, link.id)


def test_sharing_is_limited_by_the_plan():
    w = CWorld(entitlements=NoShares())
    with pytest.raises(ShareLimitReached):
        w.c.create_share(TINA, ShareTarget.CALL, w.call.id)


def test_share_links_are_listed_for_those_who_may_manage_them(w: CWorld):
    link, _ = w.c.create_share(TINA, ShareTarget.CALL, w.call.id)
    assert [item.id for item in w.c.shares(TINA, ShareTarget.CALL, w.call.id)] == [link.id]
    with pytest.raises(Forbidden):
        w.c.shares(SAM, ShareTarget.CALL, w.call.id)


# --- the email-verification policy ---------------------------------------------------------------


def test_the_policy_can_require_a_verified_email_to_submit_and_to_share():
    w = CWorld(policy=VerificationPolicy(frozenset({Action.SUBMIT, Action.INVITE})))
    with pytest.raises(VerificationRequired) as e:
        w.essay(SAM)
    assert e.value.action is Action.SUBMIT
    with pytest.raises(VerificationRequired):
        w.c.create_share(TINA, ShareTarget.CALL, w.call.id)
    assert w.c.call_view(SAM, w.call.id).can_submit  # the form is shown; the action is refused


def test_the_default_policy_lets_unverified_students_submit(w: CWorld):
    assert w.essay(SAM).id  # all test users are unverified
