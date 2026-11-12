import pytest

from previewit.application.artifacts import (
    ArtifactError,
    ArtifactRegistry,
    ArtifactType,
    UnknownArtifactType,
    Upload,
)
from previewit.plugins.pdf import PdfArtifact
from previewit.plugins.text import TextArtifact

PDF = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"


def test_both_builtins_satisfy_the_plugin_api():
    assert isinstance(TextArtifact(), ArtifactType)
    assert isinstance(PdfArtifact(), ArtifactType)


def test_text_is_normalised_and_stored_as_utf8():
    a = TextArtifact().ingest(Upload(text="  Hello\r\nwörld \r\n"))
    assert a.type_key == "text" and a.content == "Hello\nwörld".encode()
    assert a.media_type.startswith("text/plain") and a.size == len(a.content)


@pytest.mark.parametrize("text", [None, "", "   \n "])
def test_empty_text_is_refused(text):
    with pytest.raises(ArtifactError):
        TextArtifact().ingest(Upload(text=text))


def test_too_long_text_is_refused():
    with pytest.raises(ArtifactError, match="too long"):
        TextArtifact().ingest(Upload(text="x" * 400_001))


def test_text_is_escaped_when_rendered():
    a = TextArtifact().ingest(Upload(text="<script>alert(1)</script> & more"))
    html = TextArtifact().render_html(a, "/raw")
    assert "<script>" not in html and "&lt;script&gt;" in html and "&amp;" in html


def test_pdf_is_accepted_and_the_filename_is_made_safe():
    a = PdfArtifact().ingest(Upload(content=PDF, filename="..\\evil/<my report>.pdf"))
    assert a.type_key == "pdf" and a.media_type == "application/pdf" and a.content == PDF
    assert a.filename is not None and "/" not in a.filename and "<" not in a.filename
    assert a.filename.endswith(".pdf")


@pytest.mark.parametrize(
    ("content", "message"),
    [(None, "Choose"), (b"", "Choose"), (b"GIF89a", "not a PDF"), (b"x" * 10_000_001, "too large")],
)
def test_bad_pdfs_are_refused(content, message):
    with pytest.raises(ArtifactError, match=message):
        PdfArtifact().ingest(Upload(content=content, filename="a.pdf"))


def test_pdf_render_escapes_the_url():
    a = PdfArtifact().ingest(Upload(content=PDF))
    html = PdfArtifact().render_html(a, '/raw?"><script>')
    assert "<script>" not in html and "application/pdf" in html


def test_registry_lookup_listing_and_duplicates():
    reg = ArtifactRegistry([TextArtifact(), PdfArtifact()])
    assert reg.get("pdf").label == "PDF" and [t.key for t in reg.all()] == ["text", "pdf"]
    with pytest.raises(UnknownArtifactType):
        reg.get("code")
    with pytest.raises(ValueError, match="twice"):
        reg.register(TextArtifact())
