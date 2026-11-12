import uuid

import pytest
from playwright.sync_api import Browser, Page, expect

pytestmark = pytest.mark.acceptance

PASSWORD = "correct horse battery"


def _sign_up(page: Page, base_url: str, name: str, next_: str = "/spaces") -> str:
    email = f"{uuid.uuid4().hex[:8]}@example.org"
    page.goto(f"{base_url}/signup?next={next_}")
    page.get_by_label("Name").fill(name)
    page.get_by_label("Email").fill(email)
    page.get_by_label("Password").fill(PASSWORD)
    page.get_by_role("button", name="Sign up").click()
    return email


def test_teacher_invites_a_student_who_joins_and_is_put_in_a_group(
    page: Page, browser: Browser, base_url: str
):
    # Teacher: organization, course, invitation link
    _sign_up(page, base_url, "Tina Teacher")
    expect(page.get_by_role("heading", name="Your spaces")).to_be_visible()
    page.get_by_label("Name").fill("Jyväskylä School")
    page.get_by_role("button", name="Create organization").click()
    page.get_by_label("Name").fill("Software Engineering")
    page.get_by_role("button", name="Create course").click()
    expect(page.get_by_role("heading", name="Software Engineering", level=1)).to_be_visible()

    page.get_by_role("button", name="Create invite link").click()
    link = page.locator("code.link").inner_text()
    assert "/join/" in link

    # Student, in another browser: follows the link, signs up, joins
    student_context = browser.new_context()
    try:
        student = student_context.new_page()
        student.goto(link)
        expect(student.get_by_role("heading", name="Join Software Engineering")).to_be_visible()
        student.get_by_role("link", name="Create an account").click()
        student.get_by_label("Name").fill("Sam Student")
        student.get_by_label("Email").fill(f"{uuid.uuid4().hex[:8]}@example.org")
        student.get_by_label("Password").fill(PASSWORD)
        student.get_by_role("button", name="Sign up").click()
        student.get_by_role("button", name="Join").click()
        expect(student.get_by_role("heading", name="Software Engineering", level=1)).to_be_visible()
        expect(student.get_by_role("button", name="Create invite link")).to_have_count(0)

        # Teacher sees the student and groups them
        page.reload()
        expect(page.get_by_text("Sam Student")).to_be_visible()
        page.get_by_label("Name").last.fill("Team Red")
        page.get_by_role("button", name="Create group").click()
        page.get_by_role("button", name="Add", exact=True).click()
        expect(page.locator(".group")).to_contain_text("Sam Student")

        student.reload()
        expect(student.locator(".group")).to_contain_text("Team Red")
    finally:
        student_context.close()


def test_organizer_chooses_roles_in_a_link_and_changes_them_later(
    page: Page, browser: Browser, base_url: str
):
    _sign_up(page, base_url, "Olga Organizer")
    page.get_by_label("Name").fill("Open Source Review")
    page.get_by_role("button", name="Create organization").click()
    page.get_by_label("Name").fill("Release review")
    page.get_by_role("button", name="Create course").click()

    # A link for reviewers only: tick Reviewer, untick Author
    page.get_by_role("group", name="Roles", exact=True).get_by_label("Author").uncheck()
    page.get_by_role("button", name="Create invite link").click()
    link = page.locator("code.link").inner_text()

    guest_context = browser.new_context()
    try:
        guest = guest_context.new_page()
        guest.goto(link)
        expect(guest.get_by_text("invites you as")).to_contain_text("Reviewer")
        guest.get_by_role("link", name="Create an account").click()
        guest.get_by_label("Name").fill("Gus Guest")
        guest.get_by_label("Email").fill(f"{uuid.uuid4().hex[:8]}@example.org")
        guest.get_by_label("Password").fill(PASSWORD)
        guest.get_by_role("button", name="Sign up").click()
        guest.get_by_role("button", name="Join").click()
        expect(guest.get_by_role("button", name="Create invite link")).to_have_count(0)

        # The organizer also makes Gus an organizer (a teacher, in the Education preset)
        page.reload()
        member = page.locator("li", has_text="Gus Guest")
        member.get_by_label("Teacher").check()  # the Education word for organizer
        member.get_by_role("button", name="Change roles").click()
        guest.reload()
        expect(guest.get_by_role("button", name="Create invite link")).to_be_visible()
    finally:
        guest_context.close()
