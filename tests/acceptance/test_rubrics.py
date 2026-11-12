import pytest
from playwright.sync_api import Browser, Page, expect
from tests.acceptance.test_calls import PASSWORD, TeacherPage

pytestmark = pytest.mark.acceptance


class RubricsPage:
    """The teacher's rubric library and builder."""

    def __init__(self, page: Page) -> None:
        self.page = page

    def open_from_space(self) -> None:
        self.page.get_by_role("link", name="Software Engineering").click()
        self.page.get_by_role("link", name="Rubrics").click()
        expect(self.page.get_by_role("heading", name="Rubrics", level=1)).to_be_visible()

    def create_from_template(self, name: str, template: str) -> None:
        self.page.get_by_label("Name").fill(name)
        self.page.get_by_label("Start from").select_option(value=template)
        self.page.get_by_role("button", name="Create rubric").click()
        self.page.wait_for_url("**/rubrics/*")
        expect(self.page.get_by_role("heading", name=name, level=1)).to_be_visible()

    def add_yes_no(self, title: str) -> None:
        self.page.locator("details.card", has_text="Yes or no").locator("summary").click()
        self.page.locator("details.card[open]").get_by_label("Title").fill(title)
        self.page.get_by_role("button", name="Add yes or no criterion").click()
        expect(self.page.get_by_text(title).first).to_be_visible()


def test_teacher_builds_a_rubric_attaches_it_and_the_student_sees_it(
    page: Page, browser: Browser, base_url: str
):
    teacher = TeacherPage(page, base_url)
    join_link = teacher.create_course()
    teacher.create_assignment("Essay one")

    rubrics = RubricsPage(page)
    rubrics.open_from_space()
    rubrics.create_from_template("Essay rubric", "essay-feedback")
    expect(page.locator(".rubric-preview fieldset")).not_to_have_count(0)
    rubrics.add_yes_no("Has a thesis")

    # Attach it to the assignment from the assignment's settings
    page.get_by_role("link", name="Software Engineering").click()
    page.get_by_role("link", name="Assignments").click()
    page.get_by_role("link", name="Essay one").click()
    page.get_by_label("Review rubric").select_option(label="Essay rubric")
    page.get_by_role("button", name="Use this rubric").click()
    expect(page.get_by_role("heading", name="Review rubric: Essay rubric")).to_be_visible()

    student_ctx = browser.new_context()
    try:
        student = student_ctx.new_page()
        student.goto(join_link)
        student.get_by_role("link", name="Create an account").click()
        student.get_by_label("Name").fill("Sam Student")
        student.get_by_label("Email").fill("sam-rubric@example.org")
        student.get_by_label("Password").fill(PASSWORD)
        student.get_by_role("button", name="Sign up").click()
        student.get_by_role("button", name="Join").click()
        student.get_by_role("link", name="Assignments").click()
        student.get_by_role("link", name="Essay one").click()
        expect(student.get_by_role("heading", name="Review rubric: Essay rubric")).to_be_visible()
        expect(student.get_by_text("Has a thesis")).to_be_visible()
        expect(student.get_by_role("link", name="Manage rubrics")).to_have_count(0)
    finally:
        student_ctx.close()
