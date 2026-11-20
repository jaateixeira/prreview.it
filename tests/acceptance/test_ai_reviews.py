"""AI reviews (ADR 0025): an author sends their work to people and asks a free AI model too;
the AI review appears on the work's page, for the author only."""

import pytest
from playwright.sync_api import Browser, Page, expect
from tests.acceptance.test_request_a_review import RequestReviewPage, invitation_link, unique

pytestmark = pytest.mark.acceptance


class AiStep:
    """The optional step of the request form that suggests AI models."""

    def __init__(self, page: Page) -> None:
        self.page = page

    def say_yes(self) -> None:
        self.page.get_by_role("button", name="Yes, suggest AI models").click()
        expect(self.page.get_by_text("Choose up to 3.")).to_be_visible()

    def choose(self, name: str) -> None:
        self.page.get_by_role("checkbox", name=name).check()


def test_an_author_gets_an_ai_review_that_reviewers_never_see(
    page: Page, browser: Browser, base_url: str, outbox, writer
) -> None:
    form = RequestReviewPage(page, base_url)
    form.sign_up_from_the_home_page("Ada Author", unique("ada"))
    form.title("On trust")
    page.get_by_label("or paste the text").fill("Trust grows when tests are kept honest. " * 20)
    reviewer = unique("rita")
    form.type_reviewers(reviewer)

    ai = AiStep(page)
    ai.say_yes()
    expect(page.get_by_text("Free", exact=True).first).to_be_visible()
    expect(page.get_by_text("Runs at: Previewit's own server, Finland")).to_be_visible()
    expect(page.get_by_text("See more models")).to_be_visible()
    ai.choose("qwen3:8b")
    form.send()

    expect(page.get_by_text("qwen3:8b is reading your work.")).to_be_visible()
    link = invitation_link_or_none(page)
    page.get_by_role("link", name="your work's page").first.click()
    reviews = page.locator("#ai-reviews")
    expect(reviews.get_by_role("heading", name="AI reviews")).to_be_visible()
    expect(reviews.get_by_text("A thoughtful essay.")).to_be_visible(timeout=15_000)
    expect(reviews.get_by_text("Reviewers never do.")).to_be_visible()
    assert ("local/qwen3:8b", "") in writer.asked

    # The reviewer opens their invitation: the work is there, the AI review is not.
    other = browser.new_context().new_page()
    other.goto(link or invitation_link(outbox, reviewer))
    expect(other.get_by_text("On trust").first).to_be_visible()
    expect(other.get_by_text("A thoughtful essay.")).to_have_count(0)
    other.context.close()


def invitation_link_or_none(page: Page) -> str | None:
    """The personal link shown once on the done page, when it was not emailed."""
    box = page.locator("input.link-box").first
    return box.input_value() if box.count() else None
