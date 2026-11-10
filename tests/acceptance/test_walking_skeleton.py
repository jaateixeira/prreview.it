import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.acceptance


def test_visitor_sees_landing_page_and_htmx_swap_works(page: Page, base_url: str):
    page.goto(base_url)
    expect(page.get_by_role("heading", level=1)).to_contain_text("reviewed by peers")

    page.get_by_role("button", name="Check status").click()

    expect(page.locator("#status")).to_contain_text("All systems go")
    assert page.url.rstrip("/") == base_url  # swapped in place, no navigation
