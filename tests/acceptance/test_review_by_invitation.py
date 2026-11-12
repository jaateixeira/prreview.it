"""Processes 2 and 3 (ADR 0017): organizing peer review, then reviewing by invitation."""

import uuid

import pytest
from playwright.sync_api import Browser, Page, expect
from tests.acceptance.test_calls import PASSWORD, TeacherPage
from tests.acceptance.test_rounds import RoundsPage, join_and_submit

pytestmark = pytest.mark.acceptance


def test_organizer_invites_a_reviewer_who_opens_the_link_and_finds_the_work(
    page: Page, browser: Browser, base_url: str, outbox
):
    teacher = TeacherPage(page, base_url)
    join_link = teacher.create_course()
    teacher.create_assignment("Essay one")
    author_ctx, _ = join_and_submit(browser, base_url, join_link, "Sam", "On testing")
    reviewer_ctx = browser.new_context()
    try:
        # Process 2: the organizer sets up a round and invites a reviewer by email
        page.reload()
        RoundsPage(page).open_from_assignment()
        RoundsPage(page).create("1", "manual")
        email = f"{uuid.uuid4().hex[:8]}@example.org"
        page.get_by_text("Invite a reviewer by email").click()
        page.get_by_label("Email address").fill(email)
        page.get_by_role("checkbox", name="On testing (Sam)").check()
        page.get_by_role("button", name="Create invitation for round 1").click()
        link = page.locator("code.link").inner_text()
        assert "/i/" in link
        expect(page.get_by_text(f"{email}: waiting, 1 to review")).to_be_visible()

        # Process 3: the invited person signs up with that address, confirms it and reviews
        reviewer = reviewer_ctx.new_page()
        reviewer.goto(link)
        expect(reviewer.get_by_text("Tina Teacher invited you to review")).to_be_visible()
        expect(reviewer.get_by_text("Sam")).to_have_count(0)  # no author names for strangers
        reviewer.get_by_role("link", name="Create an account").click()
        reviewer.get_by_label("Name").fill("Rita Reviewer")
        reviewer.get_by_label("Email").fill(email)
        reviewer.get_by_label("Password").fill(PASSWORD)
        reviewer.get_by_role("button", name="Sign up").click()
        expect(reviewer.get_by_text("Confirm your email address first")).to_be_visible()

        reviewer.goto(outbox.link_for(email))
        reviewer.get_by_role("button", name="Confirm email").click()
        expect(reviewer.get_by_role("heading", name="Email confirmed")).to_be_visible()

        reviewer.goto(link)
        reviewer.get_by_role("button", name="Start reviewing").click()
        expect(reviewer.get_by_role("heading", name="My reviews", level=1)).to_be_visible()
        cards = reviewer.locator("li.card")
        expect(cards).to_have_count(1)
        expect(cards.first).to_contain_text("On testing")

        page.reload()
        expect(page.get_by_text(f"{email}: accepted (Rita Reviewer)")).to_be_visible()
    finally:
        reviewer_ctx.close()
        author_ctx.close()


def test_a_revoked_invitation_stops_working(page: Page, browser: Browser, base_url: str):
    teacher = TeacherPage(page, base_url)
    teacher.create_course()
    teacher.create_assignment("Essay one")
    page.get_by_role("link", name="Review rounds").click()
    RoundsPage(page).create("1", "manual")
    page.get_by_text("Invite a reviewer by email").click()
    page.get_by_label("Email address").fill("someone@example.org")
    page.get_by_role("button", name="Create invitation for round 1").click()
    link = page.locator("code.link").inner_text()
    page.get_by_role("button", name="Revoke").click()
    expect(page.get_by_text("someone@example.org: revoked")).to_be_visible()

    stranger_ctx = browser.new_context()
    try:
        stranger = stranger_ctx.new_page()
        stranger.goto(link)
        expect(stranger.get_by_role("heading", name="Invitation not valid")).to_be_visible()
    finally:
        stranger_ctx.close()
