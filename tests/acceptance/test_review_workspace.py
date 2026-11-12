import pytest
from playwright.sync_api import Browser, Page, expect
from tests.acceptance.test_calls import TeacherPage
from tests.acceptance.test_rounds import RoundsPage, join_and_submit
from tests.acceptance.test_rubrics import RubricsPage

pytestmark = pytest.mark.acceptance


class ReviewPage:
    """A reviewer's workspace: the work on the left, the rubric form and comments on the right."""

    def __init__(self, page: Page) -> None:
        self.page = page

    def open_first_task(self) -> None:
        self.page.get_by_role("link", name="Spaces").first.click()
        self.page.get_by_role("link", name="Software Engineering").click()
        self.page.get_by_role("link", name="My reviews").click()
        self.page.locator("li.card a").first.click()
        expect(self.page.get_by_role("heading", name="The work", exact=True)).to_be_visible()

    def select_text(self, word: str) -> None:
        self.page.evaluate(
            """(word) => {
              const pre = document.querySelector('[data-annotatable] pre');
              const node = pre.firstChild;
              const i = node.textContent.indexOf(word);
              window.getSelection().setBaseAndExtent(node, i, node, i + word.length);
            }""",
            word,
        )

    def add_comment(self, word: str, comment: str) -> None:
        self.select_text(word)
        expect(self.page.locator("#comment-selected")).to_contain_text(word)
        self.page.get_by_label("Comment", exact=True).last.fill(comment)
        self.page.get_by_role("button", name="Add comment").click()
        expect(self.page.locator("#comments")).to_contain_text(comment)


def test_reviewer_answers_with_autosave_pins_a_comment_and_submits(
    page: Page, browser: Browser, base_url: str
):
    teacher = TeacherPage(page, base_url)
    join_link = teacher.create_course()
    teacher.create_assignment("Essay one")
    rubrics = RubricsPage(page)
    rubrics.open_from_space()
    rubrics.create_from_template("Quick rubric", "quick-check")
    page.get_by_role("link", name="Software Engineering").click()
    page.get_by_role("link", name="Assignments").click()
    page.get_by_role("link", name="Essay one").click()
    page.get_by_label("Review rubric").select_option(label="Quick rubric")
    page.get_by_role("button", name="Use this rubric").click()

    contexts = []
    try:
        sam_ctx, _sam = join_and_submit(browser, base_url, join_link, "Sam", "On testing")
        sue_ctx, sue = join_and_submit(browser, base_url, join_link, "Sue", "On design")
        contexts += [sam_ctx, sue_ctx]

        page.reload()
        page.get_by_role("link", name="Review rounds").click()
        rounds = RoundsPage(page)
        rounds.create("1", "round_robin")
        rounds.allocate()
        expect(page.get_by_text("Allocated 2 reviews.")).to_be_visible()

        review = ReviewPage(sue)
        review.open_first_task()
        expect(sue.locator(".artifact")).to_contain_text("Text of On testing")

        # Answering saves by itself: no button pressed
        sue.get_by_label("Yes").check()
        expect(sue.locator("#version")).to_have_value("1")  # the first save happened
        score = sue.locator("fieldset", has_text="Overall score").locator("input")
        score.fill("4")
        score.blur()
        expect(sue.locator("#version")).to_have_value("2")
        sue.reload()
        expect(sue.get_by_label("Yes")).to_be_checked()
        expect(sue.locator("fieldset", has_text="Overall score").locator("input")).to_have_value(
            "4"
        )

        # A comment pinned to selected words
        review.add_comment("testing", "Nice phrase")

        # Required answers are enforced on submit only
        sue.get_by_role("button", name="Submit review").click()
        expect(sue.get_by_role("alert")).to_contain_text("required questions: Comment")
        sue.locator("fieldset", has_text="One thing").locator("textarea").fill("Well argued")
        sue.get_by_role("button", name="Submit review").click()
        expect(sue.get_by_text("Review submitted")).to_be_visible()

        # The teacher sees it, read only
        page.reload()
        expect(page.get_by_role("link", name="submitted")).to_have_count(1)
    finally:
        for ctx in contexts:
            ctx.close()
