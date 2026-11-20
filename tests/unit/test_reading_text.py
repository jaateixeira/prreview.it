"""Artifact types that AI models can read as plain text (ADR 0025)."""

from __future__ import annotations

import pytest

from previewit.application.artifacts import ArtifactError, PluginServices, ReadsText, Upload
from previewit.plugins.pdf import PdfArtifact
from previewit.plugins.text import TextArtifact
from previewit.plugins.webpage import WebPageArtifact
from tests.unit.test_webpage_plugin import ESSAY, FakePageChecker


def pdf_with_text(*pages: str) -> bytes:
    """A small but real PDF whose pages say `pages`, in Helvetica."""
    count = len(pages)
    kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(count))
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{kids}] /Count {count} >>".encode(),
    ]
    font = 3 + 2 * count
    for i, words in enumerate(pages):
        content = f"BT /F1 12 Tf 72 712 Td ({words}) Tj ET".encode()
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 "
            f"{font} 0 R >> >> /Contents {4 + 2 * i} 0 R >>".encode()
        )
        objects.append(b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref,
    )
    return bytes(out)


def test_text_reads_as_itself() -> None:
    plugin = TextArtifact()
    assert isinstance(plugin, ReadsText)
    assert plugin.text_of(plugin.ingest(Upload(text="Hyvää päivää"))) == "Hyvää päivää"


def test_a_pdf_reads_page_by_page() -> None:
    plugin = PdfArtifact()
    artifact = plugin.ingest(Upload(content=pdf_with_text("First page", "Second page")))
    text = plugin.text_of(artifact)
    assert "First page" in text and "Second page" in text
    assert text.index("First") < text.index("Second")


def test_a_pdf_without_text_says_so() -> None:
    plugin = PdfArtifact()
    with pytest.raises(ArtifactError, match="no text"):
        plugin.text_of(plugin.ingest(Upload(content=pdf_with_text(""))))
    with pytest.raises(ArtifactError, match="could not read"):
        plugin.text_of(plugin.ingest(Upload(content=b"%PDF-1.4\nnot really a pdf")))


def test_a_web_page_is_read_when_asked() -> None:
    pages = FakePageChecker({ESSAY.address: ESSAY}, texts={ESSAY.address: "On testing and trust."})
    plugin = WebPageArtifact()
    plugin.connect(PluginServices(pages=pages, reader=pages))
    artifact = plugin.ingest(Upload(url=ESSAY.address))
    assert plugin.text_of(artifact) == "On testing and trust."


def test_without_a_reader_a_web_page_cannot_be_read() -> None:
    plugin = WebPageArtifact(FakePageChecker({ESSAY.address: ESSAY}))
    artifact = plugin.ingest(Upload(url=ESSAY.address))
    with pytest.raises(ArtifactError, match="cannot read web pages"):
        plugin.text_of(artifact)
