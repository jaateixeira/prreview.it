"""Process 1 in a few clicks (ADR 0018): sign up, add a file and reviewers, send it out."""

import re
import uuid

import pytest
from playwright.sync_api import Browser, Page, expect
from tests.acceptance.test_calls import PASSWORD

pytestmark = pytest.mark.acceptance

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


def unique(name: str) -> str:
    return f"{name}.{uuid.uuid4().hex[:8]}@example.org"


class RequestReviewPage:
    """The single page where a review is requested."""

    def __init__(self, page: Page, base_url: str) -> None:
        self.page, self.base_url = page, base_url

    # -- getting there -----------------------------------------------------------------------

    def sign_up_from_the_home_page(self, name: str, email: str) -> None:
        self.page.goto(self.base_url)
        self.page.get_by_role("link", name="Request a review").first.click()
        self.page.get_by_role("link", name="Create an account").click()
        self.page.get_by_label("Name").fill(name)
        self.page.get_by_label("Email").fill(email)
        self.page.get_by_label("Password").fill(PASSWORD)
        self.page.get_by_role("button", name="Sign up").click()
        expect(self.page.get_by_role("heading", name="Get your work reviewed")).to_be_visible()

    def confirm_email(self, outbox, email: str) -> None:
        tab = self.page.context.new_page()
        tab.goto(outbox.link_for(email))
        tab.get_by_role("button", name="Confirm email").click()
        expect(tab.get_by_role("heading", name="Email confirmed")).to_be_visible()
        tab.close()
        self.page.reload()

    # -- the three steps ---------------------------------------------------------------------

    def title(self, text: str) -> None:
        self.page.get_by_label("Title").fill(text)

    def attach(self, name: str, content: bytes, mime: str) -> None:
        self.page.get_by_label("A PDF or text file").set_input_files(
            files=[{"name": name, "mimeType": mime, "buffer": content}]
        )

    def type_reviewers(self, text: str) -> None:
        self.page.get_by_label("Email addresses").fill(text)

    def import_list(self, name: str, content: bytes, mime: str) -> None:
        self.page.get_by_label("or import a list").set_input_files(
            files=[{"name": name, "mimeType": mime, "buffer": content}]
        )

    def send(self) -> None:
        self.page.get_by_role("button", name="Send it out").click()


def invitation_link(outbox, email: str) -> str:
    body = next(b for to, _, b in reversed(outbox.sent) if to == email and "/i/" in b)
    match = re.search(r"https?://\S+/i/[\w-]+", body)
    assert match, body
    return match.group(0)


def test_someone_new_requests_a_review_in_a_few_clicks_and_reviewers_find_the_work(
    page: Page, browser: Browser, base_url: str, outbox
):
    ana, cy = unique("ana"), unique("cy")
    organizer = unique("maya")
    request = RequestReviewPage(page, base_url)
    request.sign_up_from_the_home_page("Maya Maker", organizer)

    # Previewit mails in her name, so it asks her to confirm her address first
    expect(page.get_by_text("Confirm your email address first")).to_be_visible()
    expect(page.get_by_label("Email the invitations for me")).to_be_disabled()
    request.confirm_email(outbox, organizer)
    expect(page.get_by_label("Email the invitations for me")).to_be_checked()

    # 1. the work
    request.title("My thesis chapter")
    request.attach("chapter.pdf", PDF, "application/pdf")

    # 2. the people: a typo is caught while typing, then fixed
    request.type_reviewers(f"{ana}, bo@")
    expect(page.get_by_text("bo@ does not look like an email address")).to_be_visible()
    expect(page.get_by_text("1 reviewer ready")).to_be_visible()
    request.type_reviewers(ana)
    expect(page.get_by_text("bo@ does not look like")).to_have_count(0)

    # ...a list from a file adds the rest, and a sample shows the formats that work
    request.import_list("team.csv", f"name,email\nCy,{cy}\n".encode(), "text/csv")
    expect(page.get_by_text("2 reviewers ready")).to_be_visible()
    expect(page.get_by_label("Email addresses")).to_have_value(re.compile(re.escape(cy)))
    page.get_by_text("See a sample").click()
    expect(page.locator(".sample pre").first).to_contain_text("example.org")
    expect(page.get_by_role("link", name="Download").first).to_be_visible()

    # 3. send
    page.get_by_label("A few words for the reviewers").fill("Please be honest and quick.")
    request.send()
    expect(page.get_by_role("heading", name="Sent!")).to_be_visible()
    rows = page.locator("ul.reviewers li")
    expect(rows).to_have_count(2)
    expect(rows.filter(has_text=ana)).to_contain_text("Emailed")
    expect(rows.filter(has_text=cy)).to_contain_text("Emailed")
    shown = rows.filter(has_text=ana).locator("input.link-box").input_value()
    assert shown == invitation_link(outbox, ana)  # the link on screen is the link in the mail

    # a reviewer follows the emailed link, signs up with that address and finds the work
    reviewer_ctx = browser.new_context()
    try:
        reviewer = reviewer_ctx.new_page()
        reviewer.goto(shown)
        expect(reviewer.get_by_text("Maya Maker invited you to review")).to_be_visible()
        reviewer.get_by_role("link", name="Create an account").click()
        reviewer.get_by_label("Name").fill("Ana Author")
        reviewer.get_by_label("Email").fill(ana)
        reviewer.get_by_label("Password").fill(PASSWORD)
        reviewer.get_by_role("button", name="Sign up").click()
        reviewer.goto(outbox.link_for(ana))
        reviewer.get_by_role("button", name="Confirm email").click()
        expect(reviewer.get_by_role("heading", name="Email confirmed")).to_be_visible()
        reviewer.goto(shown)
        reviewer.get_by_role("button", name="Start reviewing").click()
        expect(reviewer.locator("li.card").first).to_contain_text("My thesis chapter")
    finally:
        reviewer_ctx.close()

    # Maya can follow how it is going
    page.get_by_role("link", name="Follow the reviews").click()
    expect(page.get_by_text(f"{ana}: accepted (Ana Author)")).to_be_visible()
    expect(page.get_by_text(f"{cy}: waiting")).to_be_visible()


def test_a_file_that_cannot_be_reviewed_is_explained_and_nothing_is_lost(page: Page, base_url: str):
    request = RequestReviewPage(page, base_url)
    request.sign_up_from_the_home_page("Maya Maker", unique("maya"))
    friend = unique("friend")
    request.attach("slides.pptx", b"PK\x03\x04\x00\x00binary", "application/vnd.ms-powerpoint")
    request.type_reviewers(friend)
    request.send()
    expect(page.get_by_role("alert").filter(has_text="PDF files and plain text")).to_be_visible()
    expect(page.get_by_label("Email addresses")).to_have_value(friend)
