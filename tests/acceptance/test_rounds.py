import uuid

import pytest
from playwright.sync_api import Browser, Page, expect
from tests.acceptance.test_calls import PASSWORD, TeacherPage

pytestmark = pytest.mark.acceptance


class RoundsPage:
    """The organizer's round setup: configure, allocate, read the pairs."""

    def __init__(self, page: Page) -> None:
        self.page = page

    def open_from_assignment(self) -> None:
        self.page.get_by_role("link", name="Review rounds").click()
        expect(self.page.get_by_role("heading", name="Review rounds", level=1)).to_be_visible()

    def create(self, reviews: str, method: str) -> None:
        form = self.page.locator("form", has=self.page.get_by_role("heading", name="Add round 1"))
        form.get_by_label("Reviews each submission gets").fill(reviews)
        form.get_by_label("Allocation").select_option(value=method)
        form.get_by_role("button", name="Create round").click()
        expect(self.page.get_by_role("heading", name="Round 1")).to_be_visible()

    def allocate(self) -> None:
        self.page.get_by_role("button", name="Allocate reviewers (round 1)").click()


def join_and_submit(browser: Browser, base_url: str, join_link: str, name: str, title: str):
    ctx = browser.new_context()
    student = ctx.new_page()
    student.goto(join_link)
    student.get_by_role("link", name="Create an account").click()
    student.get_by_label("Name").fill(name)
    student.get_by_label("Email").fill(f"{uuid.uuid4().hex[:8]}@example.org")
    student.get_by_label("Password").fill(PASSWORD)
    student.get_by_role("button", name="Sign up").click()
    student.get_by_role("button", name="Join").click()
    student.get_by_role("link", name="Assignments").click()
    student.get_by_role("link", name="Essay one").click()
    student.get_by_label("Title").fill(title)
    student.get_by_label("Your text").fill(f"Text of {title}")
    student.get_by_role("button", name="Submit").click()
    expect(student.get_by_role("heading", name=title, level=1)).to_be_visible()
    return ctx, student


def test_teacher_allocates_peer_reviews_and_students_see_what_to_review(
    page: Page, browser: Browser, base_url: str
):
    teacher = TeacherPage(page, base_url)
    join_link = teacher.create_course()
    teacher.create_assignment("Essay one")

    contexts = []
    try:
        students = []
        for name, title in (("Sam", "On testing"), ("Sue", "On design"), ("Pat", "On speed")):
            ctx, student = join_and_submit(browser, base_url, join_link, name, title)
            contexts.append(ctx)
            students.append((name, title, student))

        rounds = RoundsPage(page)
        page.reload()
        rounds.open_from_assignment()
        rounds.create("1", "round_robin")
        rounds.allocate()
        expect(page.get_by_text("Allocated 3 reviews.")).to_be_visible()
        expect(page.locator("table tbody tr")).to_have_count(3)

        # Nobody is paired with their own work; each student sees exactly one review to do
        for _name, own_title, student in students:
            student.get_by_role("link", name="Spaces").first.click()
            student.get_by_role("link", name="Software Engineering").click()
            student.get_by_role("link", name="My reviews").click()
            cards = student.locator("li.card")
            expect(cards).to_have_count(1)
            expect(cards.first).not_to_contain_text(own_title)
            expect(cards.first).to_contain_text("round 1")
    finally:
        for ctx in contexts:
            ctx.close()
