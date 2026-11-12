"""Built-in artifact type: plain text (pasted into a box)."""

from __future__ import annotations

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
