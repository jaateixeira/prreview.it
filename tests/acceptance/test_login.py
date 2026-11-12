import uuid

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.acceptance

PASSWORD = "correct horse battery"


class AuthPages:
    """Page object for sign-up, login and the account page."""

    def __init__(self, page: Page, base_url: str) -> None:
        self.page = page
        self.base_url = base_url

    def sign_up(self, email: str, name: str = "Ann Reviewer", password: str = PASSWORD) -> None:
        self.page.goto(f"{self.base_url}/signup")
        self.page.get_by_label("Name").fill(name)
        self.page.get_by_label("Email").fill(email)
        self.page.get_by_label("Password").fill(password)
        self.page.get_by_role("button", name="Sign up").click()
        expect(self.page.get_by_role("link", name="Account")).to_be_visible()

    def log_in(self, email: str, password: str, *, succeeds: bool = True) -> None:
        self.page.goto(f"{self.base_url}/login")
        self.page.get_by_label("Email").fill(email)
        self.page.get_by_label("Password").fill(password)
        self.page.get_by_role("button", name="Log in").click()
        if succeeds:
            expect(self.page.get_by_role("link", name="Account")).to_be_visible()

    def log_out(self) -> None:
        self.page.goto(f"{self.base_url}/account")
        self.page.get_by_role("button", name="Log out").click()
        expect(self.page.get_by_role("link", name="Log in")).to_be_visible()


@pytest.fixture
def pages(page: Page, base_url: str) -> AuthPages:
    return AuthPages(page, base_url)


def _email() -> str:
    return f"{uuid.uuid4().hex[:8]}@example.org"


def test_visitor_signs_up_logs_out_and_logs_back_in(pages: AuthPages, page: Page):
    email = _email()
    pages.sign_up(email)
    page.goto(f"{pages.base_url}/account")
    expect(page.get_by_role("heading", name="Your account")).to_be_visible()
    expect(page.get_by_text(email)).to_be_visible()

    pages.log_out()
    expect(page.get_by_role("link", name="Log in")).to_be_visible()

    pages.log_in(email, PASSWORD)
    page.goto(f"{pages.base_url}/account")
    expect(page.get_by_text(email)).to_be_visible()


def test_wrong_password_shows_a_clear_error(pages: AuthPages, page: Page):
    email = _email()
    pages.sign_up(email)
    pages.log_out()
    pages.log_in(email, "not the password", succeeds=False)
    expect(page.get_by_role("alert")).to_contain_text("Wrong email or password")
