"""Built-in artifact type: PDF files."""

from __future__ import annotations

import re
from collections.abc import Mapping
from html import escape
from typing import Literal

from previewit.application.artifacts import ArtifactError, Upload
from previewit.domain.calls import Artifact


class PdfArtifact:
    key = "pdf"
    label = "PDF"
    input_kind: Literal["text", "file"] = "file"
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
