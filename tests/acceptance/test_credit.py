"""Credit (ADR 0026): what Paddle's review reads is a click away on every page, and an author
who bought credit asks an AI model without a key of their own."""

import json
import time

import httpx
import pytest
from playwright.sync_api import Page, expect
from tests.acceptance.test_ai_reviews import AiStep
from tests.acceptance.test_request_a_review import RequestReviewPage, unique

from previewit.adapters.payments.paddle import sign

pytestmark = pytest.mark.acceptance


class Footer:
    def __init__(self, page: Page) -> None:
        self.page = page

    def open(self, name: str) -> None:
        self.page.get_by_role("navigation", name="About").get_by_role("link", name=name).click()


def test_a_visitor_finds_prices_terms_refunds_and_privacy(page: Page, base_url: str) -> None:
    page.goto(base_url)
    footer = Footer(page)
    footer.open("Pricing")
    expect(page.get_by_role("heading", name="Pricing")).to_be_visible()
    expect(page.get_by_text("€10 of credit for €10")).to_be_visible()
    footer.open("Terms")
    expect(
        page.get_by_text("Paddle.com is the Merchant of Record", exact=False).first
    ).to_be_visible()
    expect(page.get_by_text("run by Sam Seller", exact=False)).to_be_visible()
    footer.open("Refunds")
    expect(page.get_by_text("within 30 days of buying it, for any reason")).to_be_visible()
    footer.open("Privacy")
    expect(page.get_by_role("heading", name="Your rights")).to_be_visible()
    footer.open("Contact")
    expect(page.get_by_role("link", name="hello@example.org").first).to_be_visible()


def test_an_author_pays_an_ai_review_from_credit(
    page: Page, base_url: str, paddle_secret: str, writer
) -> None:
    form = RequestReviewPage(page, base_url)
    form.sign_up_from_the_home_page("Cleo Credit", unique("cleo"))

    page.goto(f"{base_url}/credit")
    expect(page.get_by_text("You have €0.00 of credit.")).to_be_visible()
    expect(page.get_by_role("button", name="Buy €10")).to_be_visible()
    buyer = page.locator("#credit-buy").get_attribute("data-user")
    paddle_says_paid(base_url, paddle_secret, str(buyer))  # what Paddle sends after checkout
    page.reload()
    expect(page.get_by_text("You have €10.00 of credit.")).to_be_visible()

    page.goto(f"{base_url}/review/new")
    form.title("On credit")
    page.get_by_label("or paste the text").fill("Credit makes AI reviews simple. " * 20)
    form.type_reviewers(unique("rita"))
    ai = AiStep(page)
    ai.say_yes()
    expect(page.get_by_text("Your credit: €10.00.")).to_be_visible()
    ai.choose("Claude Sonnet 5.5")
    form.send()

    expect(page.get_by_text("Claude Sonnet 5.5 is reading your work.")).to_be_visible()
    page.get_by_role("link", name="your work's page").first.click()
    reviews = page.locator("#ai-reviews")
    expect(reviews.get_by_text("A thoughtful essay.")).to_be_visible(timeout=15_000)
    expect(reviews.get_by_text("from your credit", exact=False)).to_be_visible()
    assert ("anthropic/claude-sonnet-5-5", "sk-ant-acceptance-house-key") in writer.asked


def paddle_says_paid(base_url: str, secret: str, user_id: str) -> None:
    body = json.dumps({
        "event_type": "transaction.completed",
        "data": {
            "id": f"txn_acceptance_{user_id}", "custom_data": {"user_id": user_id},
            "items": [{"price": {"id": "pri_10"}, "quantity": 1}],
            "details": {"totals": {"grand_total": "1000"}},
        },
    }).encode()  # fmt: skip
    answer = httpx.post(
        f"{base_url}/paddle/webhook",
        content=body,
        headers={"Paddle-Signature": sign(body, secret, int(time.time()))},
    )
    assert answer.status_code == 200, answer.text
