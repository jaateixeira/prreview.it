"""The built-in web page artifact type (ADR 0022)."""

from __future__ import annotations

import json

import pytest

from previewit.application.artifacts import (
    ArtifactError,
    ArtifactRegistry,
    ArtifactType,
    NamesItself,
    PluginServices,
    Upload,
    connect_plugins,
)
from previewit.application.web_pages import PageCheck, PageUnreachable, normalise_address
from previewit.plugins.webpage import WebPageArtifact


class FakePageChecker:
    """Pages by address; a string is the reason the page cannot be reached."""

    def __init__(
        self, pages: dict[str, PageCheck | str] | None = None, texts: dict[str, str] | None = None
    ) -> None:
        self.pages = pages if pages is not None else {}
        self.texts = texts if texts is not None else {}  # what read_text finds (ADR 0025)
        self.checked: list[str] = []
        self.read: list[str] = []

    def check(self, address: str) -> PageCheck:
        url = normalise_address(address)
        self.checked.append(url)
        found = self.pages.get(url)
        if found is None:
            raise PageUnreachable("Previewit could not find that site. Check the address.")
        if isinstance(found, str):
            raise PageUnreachable(found)
        return found

    def read_text(self, address: str) -> str:
        url = normalise_address(address)
        self.read.append(url)
        found = self.pages.get(url)
        if isinstance(found, str):
            raise PageUnreachable(found)
        if url not in self.texts:
            raise PageUnreachable("Previewit could not read that page.")
        return self.texts[url]


ESSAY = PageCheck(
    "https://example.org/essay",
    "https://example.org/essay",
    'On testing & "trust"',
    "A short essay.",
    "Sam's notes",
    "text/html",
)


def plugin(**pages: PageCheck | str) -> WebPageArtifact:
    return WebPageArtifact(FakePageChecker({ESSAY.address: ESSAY, **pages}))


def test_it_is_an_artifact_type_that_takes_an_address():
    web = plugin()
    assert isinstance(web, ArtifactType) and isinstance(web, NamesItself)
    assert (web.key, web.label, web.input_kind, web.annotation_kind) == (
        "webpage",
        "Web page",
        "url",
        "",
    )


def test_an_address_becomes_a_small_record_of_the_check():
    artifact = plugin().ingest(Upload(url=" example.org/essay "))
    assert artifact.type_key == "webpage" and artifact.media_type == "application/json"
    record = json.loads(artifact.content)
    assert record["address"] == "https://example.org/essay"
    assert record["title"] == 'On testing & "trust"'
    assert plugin().title_of(artifact) == 'On testing & "trust"'


def test_a_page_that_cannot_be_reached_is_refused_with_the_reason():
    with pytest.raises(ArtifactError, match="asks for a login"):
        plugin(**{"https://example.org/private": "The page asks for a login."}).ingest(
            Upload(url="https://example.org/private")
        )
    with pytest.raises(ArtifactError, match="Paste the address"):
        plugin().ingest(Upload(url="   "))
    with pytest.raises(ArtifactError, match="not on the public internet"):
        plugin().ingest(Upload(url="http://192.168.1.1/"))


def test_without_a_checker_it_says_so():
    with pytest.raises(ArtifactError, match="cannot check web pages"):
        WebPageArtifact().ingest(Upload(url="https://example.org/essay"))


def test_the_core_lends_it_the_checker():
    web = WebPageArtifact()
    checker = FakePageChecker({ESSAY.address: ESSAY})
    connect_plugins([web], PluginServices(pages=checker))
    assert web.ingest(Upload(url=ESSAY.address)).type_key == "webpage"
    assert checker.checked == [ESSAY.address]


def test_reviewers_see_a_safe_card_with_a_link_that_opens_elsewhere():
    web = plugin()
    html = web.render_html(web.ingest(Upload(url=ESSAY.address)), "/raw/1")
    assert 'href="https://example.org/essay"' in html
    assert 'target="_blank"' in html and 'rel="noopener noreferrer nofollow"' in html
    assert "On testing &amp; &quot;trust&quot;" in html and "Sam&#x27;s notes" in html
    assert "<script" not in html


def test_a_record_with_a_strange_address_is_shown_without_a_link():
    from previewit.domain.calls import Artifact

    bad = Artifact("webpage", "application/json", json.dumps({"address": "javascript:x"}).encode())
    html = plugin().render_html(bad, "/raw/1")
    assert "href" not in html


def test_a_page_without_a_title_is_named_after_its_host():
    untitled = PageCheck("https://example.org/x", "https://example.org/x", "", "", "", "text/html")
    web = plugin(**{untitled.address: untitled})
    assert web.title_of(web.ingest(Upload(url=untitled.address))) == "example.org/x"


def test_comments_cannot_be_pinned_inside_a_web_page():
    with pytest.raises(ArtifactError, match="whole page"):
        plugin().check_selector(plugin().ingest(Upload(url=ESSAY.address)), {"quote": "x"})


def test_the_registry_finds_the_type_for_an_address():
    registry = ArtifactRegistry([plugin()])
    found = registry.for_input("url")
    assert found is not None and found.key == "webpage"
    assert registry.for_input("file") is None
