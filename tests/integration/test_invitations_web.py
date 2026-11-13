"""Processes 2 and 3 (ADR 0017) through the web layer: invite a reviewer, open the link."""

import re

from fastapi.testclient import TestClient

from tests.integration.test_calls_web import create_call, submit_text
from tests.integration.test_rounds_web import new_round, page_of, round_id
from tests.integration.test_tenancy_web import Course, post, signup
from tests.integration.web_fakes import csrf_token

EMAIL = "rita@x.fi"


def invite(c: Course, call: str, email=EMAIL, work: tuple[str, ...] = ()):
    rid = round_id(c, call)
    data = {"email": email, "submission_id": list(work)}
    return post(c.teacher, f"/rounds/{rid}/invitations", data, page=page_of(c, call)), rid


def link_in(text: str) -> str:
    match = re.search(r"/i/[A-Za-z0-9_-]+", text)
    assert match, text
    return match.group(0)


def confirm_email(c: Course, client: TestClient, email: str) -> None:
    mail = [m for m in c.h.outbox.sent if m[0] == email][-1]
    path = "/verify?token=" + re.search(r"/verify\?token=(\S+)", mail[2]).group(1)  # type: ignore[union-attr]
    token = csrf_token(client, path)
    done = client.post("/verify", data={"csrf": token, "token": path.split("token=")[1]})
    assert done.status_code == 200


def verified_visitor(c: Course, email=EMAIL, name="Rita Reviewer", next_="/spaces") -> TestClient:
    visitor = c.h.new_client()
    signup(visitor, email, name, next_=next_)
    confirm_email(c, visitor, email)
    return visitor


def course_with_round():
    c = Course()
    sam = c.join_student("sam@x.fi", "Sam Student")
    call = create_call(c, "Essay")
    sub = submit_text(sam, call, "Essay by Sam", "Please review me").headers["location"]
    new_round(c, call)
    return c, call, sub.rsplit("/", 1)[1]


def test_the_organizer_invites_a_reviewer_and_the_link_is_shown_once():
    c, call, sub = course_with_round()
    r, _ = invite(c, call, work=(sub,))
    assert r.status_code == 200 and "shown only once" in r.text
    link = link_in(r.text)
    again = c.teacher.get(page_of(c, call)).text
    assert link not in again and "rita@x.fi: waiting, 1 to review" in again


def test_a_stranger_signs_up_opens_the_link_and_reviews():
    c, call, sub = course_with_round()
    link = link_in(invite(c, call, work=(sub,))[0].text)
    visitor = c.h.new_client()
    page = visitor.get(link)
    assert page.status_code == 200 and "Tina Teacher invited you to review" in page.text
    assert "r***@x.fi" in page.text and "Sam" not in page.text  # no author names, no work
    assert "Create an account" in page.text
    visitor = verified_visitor(c, next_=link)
    r = post(visitor, link, page=link)
    assert r.status_code == 303 and r.headers["location"] == f"{c.space}/reviews"
    mine = visitor.get(f"{c.space}/reviews").text
    assert "Essay by Sam" in mine
    assert "rita@x.fi: accepted (Rita Reviewer)" in c.teacher.get(page_of(c, call)).text


def test_the_link_works_for_its_own_email_only():
    c, call, sub = course_with_round()
    link = link_in(invite(c, call, work=(sub,))[0].text)
    other = verified_visitor(c, email="mallory@x.fi", name="Mallory")
    assert "signed in with another address" in other.get(link).text
    r = post(other, link, page="/account")
    assert r.status_code == 403 and "r***@x.fi" in r.text
    assert other.get(f"{c.space}/reviews").status_code == 404  # not admitted


def test_an_unverified_email_is_asked_to_confirm_first():
    c, call, sub = course_with_round()
    link = link_in(invite(c, call, work=(sub,))[0].text)
    visitor = c.h.new_client()
    signup(visitor, EMAIL, "Rita Reviewer", next_=link)
    page = visitor.get(link).text
    assert "Confirm your email address first" in page and "Start reviewing" not in page
    r = post(visitor, link, page="/account")
    assert r.status_code == 403 and "Verify your email" in r.text


def test_a_revoked_or_unknown_link_is_not_valid():
    c, call, sub = course_with_round()
    r, rid = invite(c, call, work=(sub,))
    link = link_in(r.text)
    iid = re.search(rf"/rounds/{rid}/invitations/(\w+)/revoke", r.text).group(1)  # type: ignore[union-attr]
    done = post(c.teacher, f"/rounds/{rid}/invitations/{iid}/revoke", page=page_of(c, call))
    assert done.status_code == 303
    anon = c.h.new_client()
    assert anon.get(link).status_code == 404
    assert anon.get("/i/nonsense").status_code == 404
    assert "revoked" in c.teacher.get(page_of(c, call)).text


def test_students_cannot_invite_and_bad_input_is_reported():
    c, call, _ = course_with_round()
    sam = c.join_student("sue@x.fi", "Sue Student")
    rid = round_id(c, call)
    forbidden = post(sam, f"/rounds/{rid}/invitations", {"email": EMAIL})
    assert forbidden.status_code in (403, 404)
    bad = invite(c, call, email="not an email")[0]
    assert bad.status_code == 400 and "email address" in bad.text
    assert invite(c, call)[0].status_code == 200
    twice = invite(c, call)[0]
    assert twice.status_code == 400 and "already has an invitation" in twice.text


def test_invitation_pages_keep_the_token_out_of_referrers():
    c, call, _ = course_with_round()
    link = link_in(invite(c, call)[0].text)
    assert c.h.new_client().get(link).headers["referrer-policy"] == "same-origin"


# --- Previewit sends the invitation: generate the link, ask, then ask for a cover letter -------


def send(c: Course, rid: str, fresh_page: str, letter: str = "Please be kind."):
    token = re.search(r"/i/([A-Za-z0-9_-]+)", fresh_page).group(1)  # type: ignore[union-attr]
    data = {"token": token, "email": EMAIL, "cover_letter": letter}
    return post(c.teacher, f"/rounds/{rid}/invitations/send", data, page="/spaces"), token


def test_the_organizer_is_asked_whether_previewit_should_send_it_and_for_a_cover_letter():
    c, call, sub = course_with_round()
    created, _ = invite(c, call, work=(sub,))
    assert "Have Previewit email it to rita@x.fi" in created.text
    assert 'name="cover_letter"' in created.text and "send it yourself" in created.text
    assert c.h.outbox.sent[-1][0] != EMAIL  # nothing was sent yet


def test_previewit_mails_the_invitation_with_the_cover_letter():
    c, call, sub = course_with_round()
    confirm_email(c, c.teacher, "tina@x.fi")
    created, rid = invite(c, call, work=(sub,))
    r, token = send(c, rid, created.text, "Dear Rita, your eyes would help.")
    assert r.status_code == 200 and "Invitation sent to rita@x.fi." in r.text
    to, subject, body = c.h.outbox.sent[-1]
    assert to == EMAIL and "Essay" in subject
    assert "Dear Rita, your eyes would help." in body and f"/i/{token}" in body
    assert "rita@x.fi: waiting, 1 to review, emailed" in r.text
    assert token not in r.text  # the link is not shown again


def test_an_invitation_cannot_be_mailed_twice():
    c, call, _ = course_with_round()
    confirm_email(c, c.teacher, "tina@x.fi")
    created, rid = invite(c, call)
    send(c, rid, created.text)
    again, _ = send(c, rid, created.text)
    assert again.status_code == 400 and "already sent" in again.text
    assert len([m for m in c.h.outbox.sent if m[0] == EMAIL]) == 1


def test_the_organizer_must_have_a_verified_email_to_send():
    c, call, _ = course_with_round()
    created, rid = invite(c, call)
    r, _ = send(c, rid, created.text)
    assert r.status_code == 403 and not [m for m in c.h.outbox.sent if m[0] == EMAIL]


def test_when_the_mail_fails_the_link_is_still_there_to_copy():
    c, call, _ = course_with_round()
    confirm_email(c, c.teacher, "tina@x.fi")
    created, rid = invite(c, call)
    link = link_in(created.text)
    c.h.outbox.failing = True
    r, _ = send(c, rid, created.text)
    assert r.status_code == 502 and "could not be sent" in r.text and link in r.text
    c.h.outbox.failing = False
    assert send(c, rid, created.text)[0].status_code == 200
