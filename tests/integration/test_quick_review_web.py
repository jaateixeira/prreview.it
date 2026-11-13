"""Request a review (ADR 0018) through the web layer: one page, one submit."""

import re
from collections.abc import Mapping

from fastapi.testclient import TestClient

from tests.integration.test_tenancy_web import post, signup
from tests.integration.web_fakes import Harness, csrf_token, make_harness

NEW = "/review/new"
PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


def confirm_email(h: Harness, client: TestClient, email: str) -> None:
    mail = [m for m in h.outbox.sent if m[0] == email][-1]
    token = re.search(r"/verify\?token=(\S+)", mail[2]).group(1)  # type: ignore[union-attr]
    csrf = csrf_token(client, f"/verify?token={token}")
    assert client.post("/verify", data={"csrf": csrf, "token": token}).status_code == 200


def organizer(verified: bool = True, h: Harness | None = None) -> tuple[Harness, TestClient]:
    h = h or make_harness()
    client = h.new_client()
    signup(client, "olga@x.fi", "Olga Organizer", next_=NEW)
    if verified:
        confirm_email(h, client, "olga@x.fi")
    return h, client


def send(
    client: TestClient,
    data: Mapping[str, str] | None = None,
    files: Mapping[str, tuple[str, bytes, str]] | None = None,
):
    fields = {"csrf": csrf_token(client, NEW), "title": "My essay", "text": "Please read me."}
    fields.update(data or {})
    return client.post("/review", data=fields, files=files)


def mails_to(h: Harness, address: str) -> list[tuple[str, str, str]]:
    return [m for m in h.outbox.sent if m[0] == address and "Invitation to review" in m[1]]


# -- the way in ----------------------------------------------------------------------------


def test_a_visitor_is_sent_to_sign_in_and_comes_back_to_the_page():
    client = make_harness().client
    r = client.get(NEW)
    assert r.status_code == 303 and r.headers["location"] == "/login?next=%2Freview%2Fnew"
    assert "Continue with" not in client.get("/login?next=%2Freview%2Fnew").text  # none configured


def test_signing_up_from_the_page_lands_back_on_it():
    h = make_harness()
    client = h.new_client()
    token = csrf_token(client, "/signup?next=/review/new")
    r = client.post(
        "/signup",
        data={
            "csrf": token, "email": "n@x.fi", "password": "correct horse battery",
            "name": "Nina", "next": NEW,
        },
    )  # fmt: skip
    assert r.status_code == 303 and r.headers["location"] == NEW
    assert client.get(NEW).status_code == 200


def test_the_home_page_and_menu_lead_to_it():
    _, client = organizer()
    assert 'href="/review/new"' in make_harness().client.get("/").text
    assert 'href="/review/new"' in client.get("/account").text  # in the menu


def test_the_page_asks_for_the_file_the_people_and_offers_samples():
    _, client = organizer()
    page = client.get(NEW).text
    for expected in (
        'name="title"', 'name="file"', 'name="text"', 'name="emails"', 'name="emails_file"',
        'name="cover_letter"', 'name="due"', 'name="send_emails"', "See a sample",
        "/review/samples/reviewers.csv", "ana.author@example.org",
    ):  # fmt: skip
        assert expected in page, expected
    box = re.search(r'<input[^>]*name="send_emails"[^>]*>', page).group(0)  # type: ignore[union-attr]
    assert "checked" in box and "disabled" not in box  # on by default


def test_an_unverified_organizer_is_told_why_the_mailing_is_off():
    _, client = organizer(verified=False)
    page = client.get(NEW).text
    box = re.search(r'<input[^>]*name="send_emails"[^>]*>', page).group(0)  # type: ignore[union-attr]
    assert "disabled" in box and "checked" not in box
    assert "confirm your email address" in page.lower()


# -- checking the addresses while typing ---------------------------------------------------


def check(client: TestClient, emails: str):
    return client.post(
        "/review/emails/check", data={"csrf": csrf_token(client, NEW), "emails": emails}
    )


def test_typed_addresses_are_checked_as_fragments():
    _, client = organizer()
    r = check(client, "ana@x.fi, bo@x.fi; ana@x.fi\nnot-an-address cy@")
    assert r.status_code == 200 and "<html" not in r.text  # a fragment
    assert "2 reviewers" in r.text and "ana@x.fi" in r.text and "bo@x.fi" in r.text
    assert "not-an-address" in r.text and "cy@" in r.text and "does not look like" in r.text
    assert "1 repeated" in r.text


def test_an_empty_box_gets_a_hint_not_an_error():
    _, client = organizer()
    r = check(client, "  ")
    assert r.status_code == 200 and "Type or paste" in r.text and "error" not in r.text


def test_too_many_addresses_are_reported():
    _, client = organizer()
    r = check(client, " ".join(f"p{i}@x.fi" for i in range(101)))
    assert "100" in r.text and "too many" in r.text.lower()


def test_names_in_the_list_are_escaped():
    _, client = organizer()
    r = check(client, "<script>alert(1)</script> a@x.fi")
    assert "<script>" not in r.text


def test_checking_needs_login_and_a_token():
    h, client = organizer()
    assert h.new_client().post("/review/emails/check", data={"emails": "a@x.fi"}).status_code in (
        303, 403,
    )  # fmt: skip
    assert client.post("/review/emails/check", data={"emails": "a@x.fi"}).status_code == 403


# -- importing a file of addresses ---------------------------------------------------------


def import_file(client: TestClient, name: str, content: bytes, emails: str = ""):
    return client.post(
        "/review/emails/import",
        data={"csrf": csrf_token(client, NEW), "emails": emails},
        files={"emails_file": (name, content)},
    )


def test_a_csv_file_fills_the_box_next_to_what_was_typed():
    _, client = organizer()
    r = import_file(client, "people.csv", b"name,email\nAna,ana@x.fi\nBo,bo@x.fi\n", "zed@x.fi")
    assert r.status_code == 200
    box = re.search(r"<textarea[^>]*>(.*?)</textarea>", r.text, re.S).group(1)  # type: ignore[union-attr]
    assert box.split() == ["zed@x.fi", "ana@x.fi", "bo@x.fi"]
    assert "3 reviewers" in r.text


def test_json_xml_and_text_files_work_too():
    _, client = organizer()
    for name, content in (
        ("a.json", b'{"emails": ["ana@x.fi", "bo@x.fi"]}'),
        ("a.xml", b"<people><p><email>ana@x.fi</email></p><p><email>bo@x.fi</email></p></people>"),
        ("a.txt", b"ana@x.fi\nbo@x.fi\n"),
    ):
        r = import_file(client, name, content)
        assert "2 reviewers" in r.text, name


def test_a_bad_file_is_explained_and_the_typed_text_is_kept():
    _, client = organizer()
    r = import_file(client, "x.xml", b"<!DOCTYPE a [<!ENTITY b 'c'>]><a>ana@x.fi</a>", "keep@x.fi")
    assert r.status_code == 200 and "keep@x.fi" in r.text and 'role="alert"' in r.text
    r = import_file(client, "big.txt", b"a@x.fi\n" * 100_000)
    assert r.status_code == 200 and 'role="alert"' in r.text and "too large" in r.text.lower()
    r = client.post(
        "/review/emails/import", data={"csrf": csrf_token(client, NEW), "emails": "keep@x.fi"}
    )
    assert "keep@x.fi" in r.text and "Choose a file" in r.text


def test_samples_can_be_downloaded_and_all_parse_to_the_same_people():
    _, client = organizer()
    for name in ("reviewers.txt", "reviewers.csv", "reviewers.json", "reviewers.xml"):
        r = client.get(f"/review/samples/{name}")
        assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
        assert name in r.headers["content-disposition"]
        assert "cy@example.org" in r.text
    assert client.get("/review/samples/evil.sh").status_code == 404
    assert client.get("/review/samples/..%2Fapp.py").status_code == 404


# -- the one step --------------------------------------------------------------------------


def test_one_submit_makes_the_review_and_mails_the_reviewers():
    h, client = organizer()
    r = send(
        client,
        {
            "emails": "ana@x.fi, bo@x.fi",
            "cover_letter": "Be kind, be quick.",
            "send_emails": "on",
        },
    )
    assert r.status_code == 200
    assert "ana@x.fi" in r.text and "bo@x.fi" in r.text and "Emailed" in r.text
    ana = mails_to(h, "ana@x.fi")
    assert len(ana) == 1 and "Be kind, be quick." in ana[0][2] and "/i/" in ana[0][2]
    assert len(mails_to(h, "bo@x.fi")) == 1
    assert "My essay" in client.get("/spaces").text


def test_the_result_page_shows_each_personal_link_once_and_how_to_follow_up():
    _, client = organizer()
    r = send(client, {"emails": "ana@x.fi"})
    link = re.search(r"http://testserver/i/[A-Za-z0-9_-]+", r.text)
    assert link and "only once" in r.text
    assert re.search(r'href="/calls/\w+/rounds"', r.text)  # follow how it is going
    assert 'href="/review/new"' in r.text  # ask for another
    assert link.group(0) not in client.get("/spaces").text


def test_not_sending_gives_links_to_share_yourself():
    h, client = organizer()
    r = send(client, {"emails": "ana@x.fi"})  # checkbox absent in the form data = off
    assert r.status_code == 200 and "Not emailed" in r.text and "/i/" in r.text
    assert mails_to(h, "ana@x.fi") == []


def test_a_pdf_can_be_uploaded():
    h, client = organizer()
    r = send(
        client,
        {"text": "", "title": "", "emails": "ana@x.fi", "send_emails": "on"},
        files={"file": ("thesis_draft.pdf", PDF, "application/pdf")},
    )
    assert r.status_code == 200
    assert "thesis draft" in client.get("/spaces").text  # the title came from the file name
    assert len(mails_to(h, "ana@x.fi")) == 1


def test_a_text_file_can_be_uploaded_too():
    _, client = organizer()
    r = send(
        client,
        {"text": "", "emails": "ana@x.fi"},
        files={"file": ("notes.md", b"# Notes\nHello", "text/markdown")},
    )
    assert r.status_code == 200


def test_other_kinds_of_file_are_refused_with_advice_and_nothing_is_created():
    _, client = organizer()
    r = send(
        client,
        {"text": "", "emails": "ana@x.fi"},
        files={"file": ("slides.pptx", b"PK\x03\x04\x00\x00binary", "application/zip")},
    )
    assert r.status_code == 400 and "PDF files and plain text" in r.text
    assert r.text.count("PDF files and plain text") == 1  # said once, not repeated in the box
    assert "ana@x.fi" in r.text  # what they typed is kept
    assert "My essay" not in client.get("/spaces").text


def test_a_mistyped_address_stops_everything_and_keeps_the_form():
    h, client = organizer()
    r = send(client, {"emails": "ana@x.fi, bo@", "cover_letter": "Hello there"})
    assert r.status_code == 400 and "bo@" in r.text and "does not look like" in r.text
    assert "ana@x.fi" in r.text and "Hello there" in r.text and "Please read me." in r.text
    assert mails_to(h, "ana@x.fi") == [] and "My essay" not in client.get("/spaces").text


def test_nobody_to_ask_a_missing_file_and_a_missing_title_are_explained():
    _, client = organizer()
    assert "at least one" in send(client, {"emails": ""}).text
    assert "Choose a file or paste" in send(client, {"text": "", "emails": "a@x.fi"}).text
    assert "title" in send(client, {"title": "", "emails": "a@x.fi"}).text.lower()


def test_addresses_from_a_file_join_the_typed_ones_without_repeats():
    h, client = organizer()
    r = send(
        client,
        {"emails": "ana@x.fi", "send_emails": "on"},
        files={"emails_file": ("p.csv", b"email\nana@x.fi\nbo@x.fi\n", "text/csv")},
    )
    assert r.status_code == 200
    assert len(mails_to(h, "ana@x.fi")) == 1 and len(mails_to(h, "bo@x.fi")) == 1


def test_a_bad_address_file_is_reported_on_the_form():
    _, client = organizer()
    r = send(
        client,
        {"emails": "ana@x.fi"},
        files={"emails_file": ("p.xml", b"<!DOCTYPE a [<!ENTITY b 'c'>]><a/>", "text/xml")},
    )
    assert r.status_code == 400 and 'role="alert"' in r.text


def test_the_due_date_is_optional_and_checked():
    _, client = organizer()
    assert send(client, {"emails": "ana@x.fi", "due": "2026-12-01"}).status_code == 200
    r = send(client, {"emails": "ana@x.fi", "due": "next week"})
    assert r.status_code == 400 and "date" in r.text.lower()
    r = send(client, {"emails": "ana@x.fi", "due": "2020-01-01"})
    assert r.status_code == 400 and "due date" in r.text.lower()


def test_an_unverified_organizer_can_still_make_links_but_not_send():
    h, client = organizer(verified=False)
    r = send(client, {"emails": "ana@x.fi", "send_emails": "on"})
    assert r.status_code == 400 and "confirm your email" in r.text.lower()
    assert "My essay" not in client.get("/spaces").text
    r = send(client, {"emails": "ana@x.fi"})
    assert r.status_code == 200 and "/i/" in r.text and mails_to(h, "ana@x.fi") == []


def test_a_mail_server_that_is_down_leaves_the_link_to_copy():
    h, client = organizer()
    h.outbox.failing = True
    r = send(client, {"emails": "ana@x.fi", "send_emails": "on"})
    assert r.status_code == 200 and "Could not email" in r.text and "/i/" in r.text


def test_the_form_needs_a_token_and_a_login():
    h, client = organizer()
    assert (
        client.post("/review", data={"title": "t", "text": "x", "emails": "a@x.fi"}).status_code
        == 403
    )
    anon = h.new_client()
    assert anon.post("/review", data={"title": "t"}).status_code in (303, 403)


def test_huge_uploads_are_refused_before_reading():
    _, client = organizer()
    r = client.post(
        "/review",
        content=b"x",
        headers={"content-length": "50000000", "content-type": "multipart/form-data; boundary=x"},
    )
    assert r.status_code == 413


def test_the_reviewer_can_follow_the_emailed_link_to_the_work():
    h, client = organizer()
    send(client, {"emails": "rita@x.fi", "send_emails": "on"})
    body = mails_to(h, "rita@x.fi")[0][2]
    link = re.search(r"/i/[A-Za-z0-9_-]+", body).group(0)  # type: ignore[union-attr]
    reviewer = h.new_client()
    page = reviewer.get(link)
    assert page.status_code == 200 and "Olga Organizer invited you to review" in page.text
    signup(reviewer, "rita@x.fi", "Rita Reviewer", next_=link)
    confirm_email(h, reviewer, "rita@x.fi")
    done = post(reviewer, link, page=link)
    assert done.status_code == 303 and done.headers["location"].endswith("/reviews")
    assert "My essay" in reviewer.get(done.headers["location"]).text
