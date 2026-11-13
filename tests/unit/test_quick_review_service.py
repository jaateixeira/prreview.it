"""Request a review in one step (ADR 0018): space, file and invitations, then send."""

from datetime import timedelta

import pytest

from previewit.application.artifacts import ArtifactError, Upload
from previewit.application.ports import MailError
from previewit.application.quick_review import (
    InvalidReviewRequest,
    QuickReviewService,
    ReviewRequest,
)
from previewit.application.tenancy import VerificationRequired
from previewit.domain.identity import Email, User, UserId
from previewit.domain.tenancy import OrgRole, Role
from tests.unit.test_invitations_service import InviteWorld, Outbox
from tests.unit.test_tenancy_service import ALICE

QUINN = UserId("quinn")  # signed up a minute ago: no organization, verified email
PDF = b"%PDF-1.4\n%fake but starts like a PDF\n"
ANA, BO, CY = (Email(f"{n}@x.fi") for n in ("ana", "bo", "cy"))


class QuickWorld(InviteWorld):
    def __init__(self, *args, quinn_verified=True, **kw):
        super().__init__(*args, **kw)
        quinn = User(QUINN, "Quinn", Email("quinn@x.fi"), quinn_verified, frozenset(), False)
        self.users.add_user(quinn, None)
        self.q = QuickReviewService(
            self.t, self.c, self.rr, self.iv, self.c._artifacts, self.users, self.clock
        )

    def request(self, **kw) -> ReviewRequest:
        base = {
            "title": "My thesis",
            "upload": Upload(content=PDF, filename="thesis.pdf"),
            "reviewers": (ANA, BO),
        }
        return ReviewRequest(**{**base, **kw})


@pytest.fixture
def w() -> QuickWorld:
    return QuickWorld()


def test_one_request_makes_the_space_the_submission_the_round_and_the_invitations(w: QuickWorld):
    done = w.q.request_review(QUINN, w.request(send_emails=False))
    [(org, role)] = w.t.my_organizations(QUINN)
    assert role is OrgRole.OWNER and org.preset_key == "general" and "Quinn" in org.name
    view = w.t.space_view(QUINN, done.space_id)
    assert view.space.name == "My thesis" and view.roles == frozenset({Role.ORGANIZER, Role.AUTHOR})
    call = w.c.call_view(QUINN, done.call_id).call
    assert call.artifact_type == "pdf" and call.accepting(w.clock.now)
    [round_] = w.rr.rounds(QUINN, done.call_id)
    assert round_.round.strategy_key == "manual"
    assert [i.work for i in w.iv.invitations(QUINN, round_.round.id)] == [["My thesis"]] * 2
    assert [i.address for i in done.invites] == ["ana@x.fi", "bo@x.fi"]
    assert all(not i.sent and i.error is None for i in done.invites)
    for invite in done.invites:  # each link opens a real invitation carrying the thesis
        assert w.iv.preview(invite.token).work_count == 1  # type: ignore[union-attr]


def test_pasted_text_becomes_a_text_review_and_a_text_file_does_too(w: QuickWorld):
    done = w.q.request_review(QUINN, w.request(upload=Upload(text="Hello"), send_emails=False))
    assert w.c.call_view(QUINN, done.call_id).call.artifact_type == "text"
    file = Upload(content="Tervetuloa äiti".encode(), filename="note.txt")
    done = w.q.request_review(QUINN, w.request(upload=file, send_emails=False))
    assert w.c.call_view(QUINN, done.call_id).call.artifact_type == "text"


def test_files_that_are_neither_pdf_nor_text_are_refused_before_anything_is_made(w: QuickWorld):
    for bad in (b"\x89PNG\r\n\x1a\n\x00\x00", b"PK\x03\x04\x00docx", b""):
        with pytest.raises(ArtifactError):
            w.q.request_review(QUINN, w.request(upload=Upload(content=bad, filename="x.docx")))
    assert w.t.my_organizations(QUINN) == []


def test_previewit_mails_every_reviewer_with_the_cover_letter(w: QuickWorld):
    w.users.mark_email_verified(QUINN, Email("quinn@x.fi"))
    done = w.q.request_review(QUINN, w.request(cover_letter="Please be honest."))
    assert [i.sent for i in done.invites] == [True, True]
    assert sorted(m[0] for m in w.mail.sent) == ["ana@x.fi", "bo@x.fi"]
    assert all("Please be honest." in m[2] and "/i/" in m[2] for m in w.mail.sent)


def test_sending_needs_a_verified_email_and_checks_before_creating_anything():
    w = QuickWorld(quinn_verified=False)
    with pytest.raises(VerificationRequired):
        w.q.request_review(QUINN, w.request())
    assert w.t.my_organizations(QUINN) == [] and w.mail.sent == []
    done = w.q.request_review(QUINN, w.request(send_emails=False))  # links only: fine
    assert len(done.invites) == 2


def test_a_second_request_reuses_the_organization(w: QuickWorld):
    first = w.q.request_review(QUINN, w.request(send_emails=False))
    second = w.q.request_review(QUINN, w.request(title="Another", send_emails=False))
    assert len(w.t.my_organizations(QUINN)) == 1 and first.space_id != second.space_id


def test_a_teacher_with_an_organization_gets_the_space_in_it(w: QuickWorld):
    done = w.q.request_review(ALICE, w.request(send_emails=False))
    assert w.t.space_view(ALICE, done.space_id).organization.id == w.org_a.id


def test_a_request_needs_a_title_and_at_least_one_reviewer(w: QuickWorld):
    for bad in ({"title": "  "}, {"reviewers": ()}):
        with pytest.raises(InvalidReviewRequest):
            w.q.request_review(QUINN, w.request(send_emails=False, **bad))
    assert w.t.my_organizations(QUINN) == []


def test_the_due_date_defaults_to_two_weeks_and_must_be_in_the_future(w: QuickWorld):
    done = w.q.request_review(QUINN, w.request(send_emails=False))
    [view] = w.rr.rounds(QUINN, done.call_id)
    assert view.round.closes_at == w.clock.now + timedelta(days=14)
    with pytest.raises(InvalidReviewRequest):
        w.q.request_review(QUINN, w.request(send_emails=False, due=w.clock.now - timedelta(days=1)))


def test_reviewers_over_the_sharing_limit_are_reported_not_lost():
    class Two:
        def may_create_share(self, user_id, shares_so_far):
            return shares_so_far < 2

    w = QuickWorld(entitlements=Two())
    done = w.q.request_review(QUINN, w.request(send_emails=False, reviewers=(ANA, BO, CY)))
    assert [i.address for i in done.invites] == ["ana@x.fi", "bo@x.fi"]
    assert done.not_invited == ("cy@x.fi",)


def test_a_failing_mail_leaves_the_link_to_copy_and_the_others_sent():
    w = QuickWorld()
    w.users.mark_email_verified(QUINN, Email("quinn@x.fi"))
    flaky = Outbox()
    real = flaky.send

    def send(to, subject, body):
        if to == "bo@x.fi":
            raise MailError("mailbox full")
        real(to, subject, body)

    flaky.send = send  # type: ignore[method-assign]
    w.iv._mailer = flaky
    done = w.q.request_review(QUINN, w.request())
    by = {i.address: i for i in done.invites}
    assert by["ana@x.fi"].sent and not by["bo@x.fi"].sent
    assert by["bo@x.fi"].error and by["bo@x.fi"].token


def test_a_reviewer_who_opens_the_link_finds_the_work():
    w = QuickWorld()
    done = w.q.request_review(QUINN, w.request(send_emails=False, reviewers=(Email("rita@x.fi"),)))
    w.iv.accept(UserId("rita"), done.invites[0].token)
    assert w.titles(UserId("rita"), done.space_id) == ["My thesis"]
