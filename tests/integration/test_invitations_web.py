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


def verified_visitor(c: Course, email=EMAIL, name="Rita Reviewer", next_="/spaces") -> TestClient:
    visitor = c.h.new_client()
    signup(visitor, email, name, next_=next_)
    mail = [m for m in c.h.outbox.sent if m[0] == email][-1]
    path = "/verify?token=" + re.search(r"/verify\?token=(\S+)", mail[2]).group(1)  # type: ignore[union-attr]
    token = csrf_token(visitor, path)
    done = visitor.post("/verify", data={"csrf": token, "token": path.split("token=")[1]})
    assert done.status_code == 200
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
