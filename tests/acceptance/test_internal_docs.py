import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.acceptance


def test_visitor_can_read_the_glossary_at_its_internal_address(page: Page, base_url: str):
    response = page.request.get(f"{base_url}/docs/internal/glossary.md")

    assert response.status == 200
    assert "text/markdown" in response.headers["content-type"]
    assert "# Glossary" in response.text()
