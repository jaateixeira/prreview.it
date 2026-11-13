"""Process 2 and 3 (ADR 0017): the call for reviewers, one personal invitation per reviewer."""

from datetime import timedelta
from itertools import count

import pytest

from previewit.application.artifacts import Upload
from previewit.application.calls import ShareLimitReached
from previewit.application.invitations import (
    InvalidInvitationLink,
    InvitationsService,
    WrongEmail,
)
from previewit.application.ports import MailError
from previewit.application.tenancy import Forbidden, NotFound, VerificationRequired
from previewit.domain.identity import Email, User, UserId
from previewit.domain.invitations import InvalidInvitation
from previewit.domain.tenancy import Role
from tests.unit.test_calls_service import PAT, SAM, SUE, TINA
from tests.unit.test_rounds_service import RoundsWorld
from tests.unit.test_tenancy_service import AVA, BOB, ZED

RITA = UserId("rita")  # an outsider: no membership anywhere, a verified email


class Outbox:
    """Records the mails the service sends."""

    def __init__(self, broken: bool = False) -> None:
        self.sent: list[tuple[str, str, str]] = []
        self.broken = broken

    def send(self, to: str, subject: str, body: str) -> None:
        if self.broken:
            raise MailError("smtp is down")
        self.sent.append((to, subject, body))


class InviteWorld(RoundsWorld):
    def __init__(self, *args, entitlements=None, mail=None, verified_organizer=True, **kw):
        super().__init__(*args, **kw)
        self.mail = mail or Outbox()
        if verified_organizer:
            self.users.mark_email_verified(TINA, Email(f"{TINA}@x.fi"))
        for uid, verified in ((RITA, True), (UserId("lars"), False)):
            self.users.add_user(
                User(uid, uid.title(), Email(f"{uid}@x.fi"), verified, frozenset(), False), None
            )
        ids = count(1)
        self.iv = InvitationsService(
            self.rr._repo,
            self.c._repo,
            self.t,
            self.t._repo,
            self.users,
            entitlements or self.c._entitlements,
            lambda: f"v{next(ids)}",
            self.clock,
            mailer=self.mail,
            base_url="https://previewit.test/",
        )
        self.work_by = self.work(SAM, SUE)  # two essays to review
        self.r = self.round()

    def titles(self, user, space=None):
        return sorted(
            t.submission_title for t in self.rr.my_tasks(user, space or self.call.space_id)
        )


@pytest.fixture
def w() -> InviteWorld:
    return InviteWorld()


# --- the organizer sends the call for reviewers -------------------------------------------------


def test_an_organizer_invites_a_reviewer_and_gets_a_link_token_once(w: InviteWorld):
    inv, token = w.iv.invite(TINA, w.r.id, " Rita@X.fi ", [w.work_by[SAM].id])
    assert token and token not in inv.id  # only the hash is stored
    assert inv.email == Email("rita@x.fi")
    assert inv.submission_ids == (w.work_by[SAM].id,)
    [view] = w.iv.invitations(TINA, w.r.id)
    assert (view.email, view.status, view.work) == ("rita@x.fi", "waiting", ["sam essay"])


def test_only_organizers_invite_reviewers(w: InviteWorld):
    for user in (SAM, AVA):
        with pytest.raises(Forbidden):
            w.iv.invite(user, w.r.id, "rita@x.fi")
        with pytest.raises(Forbidden):
            w.iv.invitations(user, w.r.id)
    with pytest.raises(NotFound):
        w.iv.invite(BOB, w.r.id, "rita@x.fi")
    with pytest.raises(NotFound):
        w.iv.invite(ZED, w.r.id, "rita@x.fi")


def test_invitations_are_validated(w: InviteWorld):
    with pytest.raises(InvalidInvitation):
        w.iv.invite(TINA, w.r.id, "not an email")
    other_call = w.c.create_call(
        TINA, w.call.space_id, title="Other", artifact_type="text", published=True
    )
    foreign = w.c.submit(PAT, other_call.id, title="elsewhere", upload=Upload(text="x"))
    with pytest.raises(NotFound):
        w.iv.invite(TINA, w.r.id, "rita@x.fi", [foreign.id])
    w.iv.invite(TINA, w.r.id, "rita@x.fi")
    with pytest.raises(InvalidInvitation):  # one live invitation per person and round
        w.iv.invite(TINA, w.r.id, "RITA@x.fi")


def test_a_closed_round_cannot_be_invited_to(w: InviteWorld):
    closed = w.round(opens_at=w.clock.now - timedelta(days=2), closes_at=w.clock.now - timedelta(1))
    with pytest.raises(InvalidInvitation):
        w.iv.invite(TINA, closed.id, "rita@x.fi")


def test_invitations_count_toward_the_share_limit(w: InviteWorld):
    class Limited:
        def may_create_share(self, user_id, shares_so_far):
            return shares_so_far < 2

    limited = InviteWorld(entitlements=Limited())
    limited.iv.invite(TINA, limited.r.id, "a@x.fi")
    limited.iv.invite(TINA, limited.r.id, "b@x.fi")
    with pytest.raises(ShareLimitReached):
        limited.iv.invite(TINA, limited.r.id, "c@x.fi")


def test_the_organizer_revokes_an_invitation(w: InviteWorld):
    inv, token = w.iv.invite(TINA, w.r.id, "rita@x.fi", [w.work_by[SAM].id])
    w.iv.revoke(TINA, w.r.id, inv.id)
    assert w.iv.invitations(TINA, w.r.id)[0].status == "revoked"
    assert w.iv.preview(token) is None
    with pytest.raises(InvalidInvitationLink):
        w.iv.accept(RITA, token)
    with pytest.raises(Forbidden):
        w.iv.revoke(SAM, w.r.id, inv.id)


# --- the reviewer opens it (process 3) ------------------------------------------------------------


def test_a_stranger_with_the_invited_verified_email_becomes_a_reviewer_with_tasks(w: InviteWorld):
    _, token = w.iv.invite(TINA, w.r.id, "rita@x.fi", [w.work_by[SAM].id, w.work_by[SUE].id])
    assert w.iv.preview(token).call_title == w.call.title  # type: ignore[union-attr]
    accepted = w.iv.accept(RITA, token)
    assert (accepted.created, accepted.skipped) == (2, 0)
    assert accepted.space_id == w.call.space_id
    assert w.t.space_view(RITA, w.call.space_id).roles == frozenset({Role.REVIEWER})
    assert w.titles(RITA) == ["sam essay", "sue essay"]
    assert w.iv.invitations(TINA, w.r.id)[0].status == "accepted"


def test_opening_it_twice_is_harmless(w: InviteWorld):
    _, token = w.iv.invite(TINA, w.r.id, "rita@x.fi", [w.work_by[SAM].id])
    w.iv.accept(RITA, token)
    again = w.iv.accept(RITA, token)
    assert (again.created, again.skipped) == (0, 0)
    assert w.titles(RITA) == ["sam essay"]


def test_the_invitation_belongs_to_its_email(w: InviteWorld):
    _, token = w.iv.invite(TINA, w.r.id, "rita@x.fi", [w.work_by[SAM].id])
    with pytest.raises(WrongEmail) as caught:
        w.iv.accept(ZED, token)  # zed's address is another one
    assert caught.value.hint == "r***@x.fi"
    assert not w.t.my_spaces(ZED)


def test_an_unverified_email_must_be_confirmed_first(w: InviteWorld):
    _, token = w.iv.invite(TINA, w.r.id, "lars@x.fi", [w.work_by[SAM].id])
    with pytest.raises(VerificationRequired):
        w.iv.accept(UserId("lars"), token)
    assert not w.t.my_spaces(UserId("lars"))


def test_an_existing_author_gains_the_reviewer_role_and_keeps_theirs(w: InviteWorld):
    w.t.admit(RITA, w.call.space_id, {Role.AUTHOR})
    _, token = w.iv.invite(TINA, w.r.id, "rita@x.fi", [w.work_by[SAM].id])
    w.iv.accept(RITA, token)
    assert w.t.space_view(RITA, w.call.space_id).roles == frozenset({Role.AUTHOR, Role.REVIEWER})


def test_nobody_reviews_their_own_work_through_an_invitation(w: InviteWorld):
    w.t.admit(RITA, w.call.space_id, {Role.AUTHOR})  # rita is a member and an author
    mine = w.essay(RITA, title="rita essay")
    _, token = w.iv.invite(TINA, w.r.id, "rita@x.fi", [mine.id, w.work_by[SAM].id])
    accepted = w.iv.accept(RITA, token)
    assert (accepted.created, accepted.skipped) == (1, 1)
    assert w.titles(RITA) == ["sam essay"]


def test_an_invitation_without_work_only_admits(w: InviteWorld):
    _, token = w.iv.invite(TINA, w.r.id, "rita@x.fi")
    assert w.iv.accept(RITA, token).created == 0
    assert w.t.space_view(RITA, w.call.space_id).roles == frozenset({Role.REVIEWER})


def test_expired_unknown_and_foreign_tokens_are_refused(w: InviteWorld):
    _, token = w.iv.invite(TINA, w.r.id, "rita@x.fi", ttl=timedelta(days=1))
    w.clock.now += timedelta(days=2)
    assert w.iv.preview(token) is None
    for bad in (token, "nonsense", ""):
        with pytest.raises(InvalidInvitationLink):
            w.iv.accept(RITA, bad)
    assert w.iv.invitations(TINA, w.r.id)[0].status == "expired"


def test_an_invitation_to_a_round_that_has_closed_is_refused(w: InviteWorld):
    soon = w.round(closes_at=w.clock.now + timedelta(days=1))
    _, token = w.iv.invite(TINA, soon.id, "rita@x.fi", [w.work_by[SAM].id])
    w.clock.now += timedelta(days=2)
    with pytest.raises(InvalidInvitationLink):
        w.iv.accept(RITA, token)


def test_deleting_a_round_deletes_its_invitations(w: InviteWorld):
    _, token = w.iv.invite(TINA, w.r.id, "rita@x.fi")
    w.rr.delete_round(TINA, w.r.id)
    assert w.iv.preview(token) is None


# --- Previewit sends the invitation, with the organizer's cover letter -----------------------


def test_previewit_mails_the_invitation_with_the_cover_letter(w: InviteWorld):
    _, token = w.iv.invite(TINA, w.r.id, "rita@x.fi", [w.work_by[SAM].id])
    w.iv.send(TINA, w.r.id, token, "  Dear Rita,\nyour view on my course matters.  ")
    [(to, subject, body)] = w.mail.sent
    assert to == "rita@x.fi" and w.call.title in subject
    assert "Dear Rita,\nyour view on my course matters." in body
    assert f"https://previewit.test/i/{token}" in body
    assert "Tina" in body and "rita@x.fi" in body  # who asked, and which address works
    assert w.iv.invitations(TINA, w.r.id)[0].sent


def test_the_cover_letter_is_optional_but_not_unlimited(w: InviteWorld):
    _, token = w.iv.invite(TINA, w.r.id, "rita@x.fi")
    with pytest.raises(InvalidInvitation):
        w.iv.send(TINA, w.r.id, token, "x" * 2001)
    assert w.mail.sent == [] and not w.iv.invitations(TINA, w.r.id)[0].sent
    w.iv.send(TINA, w.r.id, token, "")
    assert f"/i/{token}" in w.mail.sent[0][2]


def test_an_invitation_is_mailed_once(w: InviteWorld):
    _, token = w.iv.invite(TINA, w.r.id, "rita@x.fi")
    w.iv.send(TINA, w.r.id, token, "Hello")
    with pytest.raises(InvalidInvitation):
        w.iv.send(TINA, w.r.id, token, "Hello again")
    assert len(w.mail.sent) == 1


def test_only_a_verified_organizer_of_that_round_can_send(w: InviteWorld):
    _, token = w.iv.invite(TINA, w.r.id, "rita@x.fi")
    for user in (SAM, AVA):
        with pytest.raises(Forbidden):
            w.iv.send(user, w.r.id, token, "")
    with pytest.raises(NotFound):
        w.iv.send(ZED, w.r.id, token, "")
    other = w.round()
    with pytest.raises(InvalidInvitationLink):  # a token belongs to its own round
        w.iv.send(TINA, other.id, token, "")
    with pytest.raises(InvalidInvitationLink):
        w.iv.send(TINA, w.r.id, "nonsense", "")
    assert w.mail.sent == []
    unverified = InviteWorld(verified_organizer=False)
    _, t2 = unverified.iv.invite(TINA, unverified.r.id, "rita@x.fi")
    with pytest.raises(VerificationRequired):  # the mail goes out in their name
        unverified.iv.send(TINA, unverified.r.id, t2, "")
    assert unverified.mail.sent == []


def test_a_revoked_or_used_invitation_is_not_mailed(w: InviteWorld):
    _, token = w.iv.invite(TINA, w.r.id, "rita@x.fi")
    w.iv.accept(RITA, token)
    with pytest.raises(InvalidInvitation):
        w.iv.send(TINA, w.r.id, token, "")
    inv2, token2 = w.iv.invite(TINA, w.r.id, "pat@x.fi")
    w.iv.revoke(TINA, w.r.id, inv2.id)
    with pytest.raises(InvalidInvitationLink):
        w.iv.send(TINA, w.r.id, token2, "")
    assert w.mail.sent == []


def test_a_mail_that_fails_leaves_the_invitation_usable_and_unsent():
    w = InviteWorld(mail=Outbox(broken=True))
    _, token = w.iv.invite(TINA, w.r.id, "rita@x.fi")
    with pytest.raises(MailError):
        w.iv.send(TINA, w.r.id, token, "Hello")
    assert not w.iv.invitations(TINA, w.r.id)[0].sent
    w.mail.broken = False
    w.iv.send(TINA, w.r.id, token, "Hello")  # trying again is allowed
    assert w.iv.accept(RITA, token).created == 0
