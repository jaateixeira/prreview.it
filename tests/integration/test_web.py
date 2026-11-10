from fastapi.testclient import TestClient

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


def test_healthz():
    assert client.get("/healthz").text == "ok"


def test_static_assets_served():
    assert client.get("/static/css/tokens.css").status_code == 200
    assert client.get("/static/js/htmx.min.js").status_code == 200
