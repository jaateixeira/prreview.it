import uuid

import pytest
from playwright.sync_api import Browser, Page, expect

pytestmark = pytest.mark.acceptance

PASSWORD = "correct horse battery"


class SignUpPage:
    def __init__(self, page: Page, base_url: str) -> None:
        self.page, self.base_url = page, base_url

    def sign_up(self, name: str, next_: str = "/spaces") -> None:
        self.page.goto(f"{self.base_url}/signup?next={next_}")
        self.page.get_by_label("Name").fill(name)
        self.page.get_by_label("Email").fill(f"{uuid.uuid4().hex[:8]}@example.org")
        self.page.get_by_label("Password").fill(PASSWORD)
        self.page.get_by_role("button", name="Sign up").click()


class TeacherPage:
    """Creates a school, a course and an assignment, and hands out the join link."""

    def __init__(self, page: Page, base_url: str) -> None:
        self.page = page
        SignUpPage(page, base_url).sign_up("Tina Teacher")

    def create_course(self) -> str:
        self.page.get_by_label("Name").fill("Jyväskylä School")
        self.page.get_by_role("button", name="Create organization").click()
        self.page.get_by_label("Name").fill("Software Engineering")
        self.page.get_by_role("button", name="Create course").click()
        self.page.get_by_role("button", name="Create invite link").click()
        return self.page.locator("code.link").inner_text()

    def create_assignment(self, title: str) -> None:
        self.page.get_by_role("link", name="Assignments").click()
        self.page.get_by_label("Title").fill(title)
        self.page.get_by_label("Kind of work").select_option("Text")
        self.page.get_by_role("button", name="Create assignment").click()
        expect(self.page.get_by_role("heading", name=title, level=1)).to_be_visible()


def test_student_submits_revises_and_shares_work_with_a_reviewer_by_link(
    page: Page, browser: Browser, base_url: str
):
    teacher = TeacherPage(page, base_url)
    join_link = teacher.create_course()
    teacher.create_assignment("Essay one")

    student_ctx = browser.new_context()
    reviewer_ctx = browser.new_context()
    try:
        # Student joins and submits text
        student = student_ctx.new_page()
        student.goto(join_link)
        student.get_by_role("link", name="Create an account").click()
        student.get_by_label("Name").fill("Sam Student")
        student.get_by_label("Email").fill(f"{uuid.uuid4().hex[:8]}@example.org")
        student.get_by_label("Password").fill(PASSWORD)
        student.get_by_role("button", name="Sign up").click()
        student.get_by_role("button", name="Join").click()
        student.get_by_role("link", name="Assignments").click()
        student.get_by_role("link", name="Essay one").click()
        student.get_by_label("Title").fill("On testing")
        student.get_by_label("Your text").fill("Tests are documentation that runs.")
        student.get_by_role("button", name="Submit").click()
        expect(student.get_by_role("heading", name="On testing", level=1)).to_be_visible()
        expect(student.locator(".artifact")).to_contain_text("Tests are documentation")

        # A second revision; the first stays readable
        student.get_by_label("Your text").fill(
            "Tests are documentation that runs, and a safety net."
        )
        student.get_by_role("button", name="Save revision").click()
        expect(student.get_by_text("Revision 2 of 2")).to_be_visible()
        student.get_by_role("link", name="Revision 1").click()
        expect(student.locator(".artifact")).not_to_contain_text("safety net")
        expect(student.get_by_text("Revision 1 of 2")).to_be_visible()

        # Student shares the work; a stranger opens the link with a minimal sign-up
        student.get_by_role("button", name="Create share link").click()
        share_link = student.locator("code.link").inner_text()
        assert "/s/" in share_link

        reviewer = reviewer_ctx.new_page()
        reviewer.goto(share_link)
        expect(reviewer.get_by_text("Sam Student shared this work with you")).to_be_visible()
        reviewer.get_by_role("link", name="Create an account").click()
        reviewer.get_by_label("Name").fill("Rita Reviewer")
        reviewer.get_by_label("Email").fill(f"{uuid.uuid4().hex[:8]}@example.org")
        reviewer.get_by_label("Password").fill(PASSWORD)
        reviewer.get_by_role("button", name="Sign up").click()
        reviewer.get_by_role("button", name="Open").click()
        expect(reviewer.get_by_role("heading", name="On testing", level=1)).to_be_visible()
        expect(reviewer.locator(".artifact")).to_contain_text("safety net")
        expect(reviewer.get_by_role("button", name="Save revision")).to_have_count(0)

        # The teacher sees the student's work from the assignment page
        page.get_by_role("link", name="Assignments").click()
        page.get_by_role("link", name="Essay one").click()
        expect(page.get_by_text("On testing")).to_be_visible()
    finally:
        student_ctx.close()
        reviewer_ctx.close()
