"""Built-in artifact type: PDF files."""

from __future__ import annotations

import io
import logging
import re
from collections.abc import Mapping
from html import escape
from typing import Literal

from pypdf import PdfReader
from pypdf.errors import PyPdfError

from previewit.application.artifacts import ArtifactError, Upload
from previewit.domain.calls import Artifact

MAX_PAGES = 1_000  # pages read for an AI review


class PdfArtifact:
    key = "pdf"
    label = "PDF"
    input_kind: Literal["text", "file", "url"] = "file"
    accept = ".pdf,application/pdf"
    max_bytes = 10_000_000
    annotation_kind = ""  # pinned comments on PDF pages come in a later release

    def ingest(self, upload: Upload) -> Artifact:
        data = upload.content or b""
        if not data:
            raise ArtifactError("Choose a PDF file first.")
        if len(data) > self.max_bytes:
            raise ArtifactError("That file is too large (limit: 10 MB).")
        if not data.startswith(b"%PDF-"):
            raise ArtifactError("That file is not a PDF.")
        return Artifact(self.key, "application/pdf", data, _safe_name(upload.filename))

    def text_of(self, artifact: Artifact) -> str:
        """The text of every page, in order (ADR 0025). A scanned PDF has none."""
        logging.getLogger("pypdf").setLevel(logging.ERROR)  # odd PDFs are common; no noise
        try:
            reader = PdfReader(io.BytesIO(artifact.content))
            pages = [(page.extract_text() or "").strip() for page in reader.pages[:MAX_PAGES]]
        except (PyPdfError, ValueError, KeyError, TypeError, OSError):
            raise ArtifactError("Previewit could not read the text of this PDF.") from None
        text = "\n\n".join(page for page in pages if page)
        if not text.strip():
            raise ArtifactError(
                "This PDF has no text to read: it may be scanned pages. Save it with its text "
                "(or run text recognition on it) and try again."
            )
        return text

    def render_html(self, artifact: Artifact, raw_url: str) -> str:
        url = escape(raw_url, quote=True)
        return (
            f'<object class="artifact-pdf" data="{url}" type="application/pdf">'
            f'<a href="{url}">Open the PDF</a></object>'
        )

    def check_selector(self, artifact: Artifact, selector: Mapping[str, str]) -> dict[str, str]:
        raise ArtifactError("Comments cannot be pinned to a PDF yet.")


def _safe_name(name: str | None) -> str | None:
    if not name:
        return None
    base = re.split(r"[\\/]", name)[-1]
    base = re.sub(r"[^\w.\- ]", "_", base).strip(" .")
    return base[:120] or None
