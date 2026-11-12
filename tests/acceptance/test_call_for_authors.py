"""Process 1 (ADR 0017): organizing a call for authors, public or protected."""

import uuid

import pytest
from playwright.sync_api import Browser, Page, expect
from tests.acceptance.test_calls import PASSWORD, TeacherPage

pytestmark = pytest.mark.acceptance


def _author_signs_up(author: Page, link_or_path: str) -> None:
    author.goto(link_or_path)
    author.get_by_role("link", name="Create an account").click()
    author.get_by_label("Name").fill("Ada Author")
    author.get_by_label("Email").fill(f"{uuid.uuid4().hex[:8]}@example.org")
    author.get_by_label("Password").fill(PASSWORD)
    author.get_by_role("button", name="Sign up").click()


def _create_call(page: Page, title: str, access: str) -> None:
    page.get_by_role("link", name="Assignments").click()
    page.get_by_label("Title").fill(title)
    page.get_by_label("Kind of work").select_option("Text")
    page.get_by_label(access).check()
    page.get_by_role("button", name="Create assignment").click()
    expect(page.get_by_role("heading", name=title, level=1)).to_be_visible()


def test_organizer_sends_a_public_call_and_an_author_submits(
    page: Page, browser: Browser, base_url: str
):
    organizer = TeacherPage(page, base_url)
    organizer.create_course()
    _create_call(page, "Open essay", "Public: anyone with the address")
    address = page.locator("code.link").inner_text()
    assert "/c/" in address and "/s/" not in address

    context = browser.new_context()
    try:
        author = context.new_page()
        _author_signs_up(author, address)
        expect(author.get_by_role("heading", name="Open essay", level=1)).to_be_visible()
        author.get_by_role("button", name="Join and submit").click()
        author.get_by_label("Title").fill("Peers and tests")
        author.get_by_label("Your text").fill("Review makes work better.")
        author.get_by_role("button", name="Submit").click()
        expect(author.get_by_role("heading", name="Peers and tests", level=1)).to_be_visible()

        page.reload()
        expect(page.get_by_text("Peers and tests")).to_be_visible()  # the organizer follows it
    finally:
        context.close()


def test_a_protected_call_is_only_for_people_with_its_link(
    page: Page, browser: Browser, base_url: str
):
    organizer = TeacherPage(page, base_url)
    organizer.create_course()
    _create_call(page, "Closed essay", "Protected: only people with a link")
    page.get_by_role("button", name="Create link with a token").click()
    link = page.locator("code.link").first.inner_text()
    assert "/s/" in link

    context = browser.new_context()
    try:
        author = context.new_page()
        _author_signs_up(author, link)
        author.get_by_role("button", name="Open").click()
        expect(author.get_by_role("heading", name="Closed essay", level=1)).to_be_visible()
        author.get_by_label("Title").fill("By invitation")
        author.get_by_label("Your text").fill("Only with the link.")
        author.get_by_role("button", name="Submit").click()
        expect(author.get_by_role("heading", name="By invitation", level=1)).to_be_visible()
    finally:
        context.close()

    # Revoked: a newcomer with the same link is refused
    page.get_by_role("button", name="Revoke").click()
    stranger_context = browser.new_context()
    try:
        stranger = stranger_context.new_page()
        stranger.goto(link)
        expect(stranger.get_by_role("button", name="Open")).to_have_count(0)
    finally:
        stranger_context.close()
