"""Built-in artifact type: plain text (pasted into a box)."""

from __future__ import annotations

from collections.abc import Mapping
from html import escape
from typing import Literal

from previewit.application.artifacts import ArtifactError, Upload
from previewit.domain.calls import Artifact


class TextArtifact:
    key = "text"
    label = "Text"
    input_kind: Literal["text", "file"] = "text"
    accept = ""
    max_bytes = 400_000
    annotation_kind = "text"

    def ingest(self, upload: Upload) -> Artifact:
        text = (upload.text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
        if not text:
            raise ArtifactError("Write or paste some text first.")
        data = text.encode("utf-8")
        if len(data) > self.max_bytes:
            raise ArtifactError("That text is too long (limit: 400 kB).")
        return Artifact(self.key, "text/plain; charset=utf-8", data)

    def render_html(self, artifact: Artifact, raw_url: str) -> str:
        return f'<pre class="artifact-text">{escape(artifact.content.decode("utf-8"))}</pre>'

    def check_selector(self, artifact: Artifact, selector: Mapping[str, str]) -> dict[str, str]:
        """A text selector is a quote and where it starts and ends, counted in characters."""
        text = artifact.content.decode("utf-8")
        try:
            start, end = int(selector.get("start", "")), int(selector.get("end", ""))
        except ValueError:
            raise ArtifactError("Select some text first.") from None
        quote = selector.get("quote", "").replace("\r\n", "\n")
        if not 0 <= start < end <= len(text) or text[start:end] != quote or not quote.strip():
            raise ArtifactError("Select some text first.")
        return {"quote": quote[:500], "start": str(start), "end": str(end)}
