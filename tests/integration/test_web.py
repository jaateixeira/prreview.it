from fastapi.testclient import TestClient

from previewit.adapters.web.app import SOURCE_URL
from previewit.bootstrap import create_app

client = TestClient(create_app())


def test_home_renders_full_page():
    r = client.get("/")
    assert r.status_code == 200
    assert "reviewed by peers" in r.text
    assert "htmx.min.js" in r.text


def test_status_fragment_is_a_fragment_not_a_page():
    r = client.get("/fragments/status", headers={"HX-Request": "true"})
    assert r.status_code == 200
    assert "<html" not in r.text
    assert "All systems go" in r.text


def test_pages_link_to_the_source_code():
    # AGPL-3.0 section 13: network users must be offered the source.
    assert f'href="{SOURCE_URL}"' in client.get("/").text


def test_healthz():
    assert client.get("/healthz").text == "ok"


def test_static_assets_served():
    assert client.get("/static/css/tokens.css").status_code == 200
    assert client.get("/static/js/htmx.min.js").status_code == 200


def test_htmx_swaps_error_pages_instead_of_ignoring_them():
    # By default htmx drops 4xx/5xx responses, so a boosted link to a 404 would look dead.
    assert '"code":"[45].."' in client.get("/").text


def test_glossary_is_served_as_markdown():
    r = client.get("/docs/internal/glossary.md")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/markdown")
    assert r.text.startswith("# Glossary")
    assert "Submission" in r.text


def test_only_the_glossary_is_served_under_docs_internal():
    assert client.get("/docs/internal/PLAN.md").status_code == 404
    assert client.get("/docs/internal/../PLAN.md").status_code in (404, 422)
