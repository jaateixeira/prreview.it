from datetime import timedelta
from urllib.parse import urlparse

from tests.integration.web_fakes import Harness, csrf_token, make_harness

PASSWORD = "correct horse battery"


def _signup(h: Harness, email="ann@x.fi"):
    token = csrf_token(h.client, "/signup")
    return h.client.post(
        "/signup",
        data={
            "csrf": token,
            "email": email,
            "password": PASSWORD,
            "name": "Ann",
            "next": "/account",
        },
    )


def _path(link: str) -> str:
    parts = urlparse(link)
    return f"{parts.path}?{parts.query}"


def test_signup_sends_a_verification_mail_and_the_account_says_unverified():
    h = make_harness()
    assert _signup(h).status_code == 303
    assert len(h.outbox.sent) == 1 and h.outbox.sent[0][0] == "ann@x.fi"
    account = h.client.get("/account").text
    assert "not verified" in account and "Resend" in account


def test_opening_the_link_does_not_verify_only_confirming_does():
    h = make_harness()
    _signup(h)
    path = _path(h.outbox.last_link())
    page = h.client.get(path)
    assert page.status_code == 200 and "Confirm" in page.text
    # a mail scanner or prefetch that only GETs the link must not consume it
    assert "not verified" in h.client.get("/account").text
    token = csrf_token(h.client, path)
    done = h.client.post("/verify", data={"csrf": token, "token": path.split("token=")[1]})
    assert done.status_code == 200 and "confirmed" in done.text.lower()
    account = h.client.get("/account").text
    assert "verified" in account and "not verified" not in account and "Resend" not in account


def test_the_link_works_once():
    h = make_harness()
    _signup(h)
    path = _path(h.outbox.last_link())
    token = csrf_token(h.client, path)
    form = {"csrf": token, "token": path.split("token=")[1]}
    assert h.client.post("/verify", data=form).status_code == 200
    again = h.client.post("/verify", data=form)
    assert again.status_code == 400 and "invalid or has expired" in again.text


def test_verify_needs_a_csrf_token_and_an_expired_link_fails():
    h = make_harness()
    _signup(h)
    path = _path(h.outbox.last_link())
    tok = path.split("token=")[1]
    assert h.client.post("/verify", data={"token": tok}).status_code == 403
    h.clock.now += timedelta(hours=25)
    token = csrf_token(h.client, path)
    assert h.client.post("/verify", data={"csrf": token, "token": tok}).status_code == 400


def test_a_link_can_be_confirmed_in_another_browser_without_logging_in():
    h = make_harness()
    _signup(h)
    path = _path(h.outbox.last_link())
    h.client.cookies.clear()
    token = csrf_token(h.client, path)
    done = h.client.post("/verify", data={"csrf": token, "token": path.split("token=")[1]})
    assert done.status_code == 200


def test_resend_is_rate_limited_then_allowed():
    h = make_harness()
    _signup(h)
    token = csrf_token(h.client, "/account")
    first = h.client.post("/account/verify/resend", data={"csrf": token})
    assert "wait" in first.text.lower() and len(h.outbox.sent) == 1
    h.clock.now += timedelta(seconds=61)
    second = h.client.post("/account/verify/resend", data={"csrf": token})
    assert "sent" in second.text.lower() and len(h.outbox.sent) == 2


def test_resend_requires_login():
    h = make_harness()
    token = csrf_token(h.client, "/login")
    assert h.client.post("/account/verify/resend", data={"csrf": token}).status_code == 303


def test_a_failing_mail_server_does_not_block_signup():
    h = make_harness()

    from previewit.application.ports import MailError

    def fail(to: str, subject: str, body: str) -> None:
        raise MailError("smtp down")

    h.outbox.send = fail  # type: ignore[method-assign]
    assert _signup(h).status_code == 303
    assert "ann@x.fi" in h.client.get("/account").text
