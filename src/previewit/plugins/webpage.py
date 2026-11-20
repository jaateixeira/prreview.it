"""Built-in artifact type: a public web page, given by its address (ADR 0022).

Previewit does not copy the page. It checks that it can reach it, keeps a small record of what
it found (the address, title, description and site), and shows reviewers a card with a link
that opens the page in a new tab. Reviewers comment on the whole page.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from html import escape
from typing import Literal

from previewit.application.artifacts import ArtifactError, PluginServices, Upload
from previewit.application.web_pages import (
    MAX_ADDRESS_LENGTH,
    PageChecker,
    PageReader,
    PageUnreachable,
    host_of,
)
from previewit.domain.calls import Artifact

MEDIA_TYPE = "application/json"


class WebPageArtifact:
    key = "webpage"
    label = "Web page"
    input_kind: Literal["text", "file", "url"] = "url"
    accept = ""
    max_bytes = MAX_ADDRESS_LENGTH
    annotation_kind = ""  # a page Previewit does not copy has no places to pin comments to

    def __init__(self, checker: PageChecker | None = None) -> None:
        self._checker = checker
        self._reader: PageReader | None = None

    def connect(self, services: PluginServices) -> None:
        self._checker = services.pages
        self._reader = services.reader

    def text_of(self, artifact: Artifact) -> str:
        """The page's text as it is now: Previewit keeps no copy (ADR 0025)."""
        if self._reader is None:
            raise ArtifactError("This Previewit cannot read web pages for AI reviews.")
        address = _record(artifact).get("final_address") or _record(artifact).get("address", "")
        try:
            text = self._reader.read_text(address)
        except PageUnreachable as problem:
            raise ArtifactError(str(problem)) from None
        if not text.strip():
            raise ArtifactError("The page has no text to read.")
        return text

    def ingest(self, upload: Upload) -> Artifact:
        address = (upload.url or upload.text or "").strip()
        if not address:
            raise ArtifactError("Paste the address of the web page.")
        if self._checker is None:
            raise ArtifactError("This Previewit cannot check web pages.")
        try:
            found = self._checker.check(address)
        except PageUnreachable as problem:
            raise ArtifactError(str(problem)) from None
        record = {
            "address": found.address,
            "final_address": found.final_address,
            "title": found.title,
            "description": found.description,
            "site_name": found.site_name,
            "media_type": found.media_type,
            "note": found.note,
        }
        content = json.dumps(record, ensure_ascii=False, sort_keys=True).encode("utf-8")
        return Artifact(self.key, MEDIA_TYPE, content)

    def title_of(self, artifact: Artifact) -> str:
        record = _record(artifact)
        if record.get("title"):
            return record["title"]
        address = record.get("address", "")
        path = address.split("://", 1)[-1].split("?", 1)[0].rstrip("/")
        return path.removeprefix("www.") or host_of(address)

    def render_html(self, artifact: Artifact, raw_url: str) -> str:
        record = _record(artifact)
        address = record.get("address", "")
        title = escape(record.get("title") or self.title_of(artifact))
        site = escape(record.get("site_name") or host_of(address))
        description = escape(record.get("description", ""))
        parts = ['<div class="artifact-webpage">', f'<p class="site">{site}</p>']
        parts.append(f"<h3>{title}</h3>")
        if description:
            parts.append(f"<p>{description}</p>")
        if address.startswith(("https://", "http://")):
            parts.append(
                f'<p><a class="btn" href="{escape(address, quote=True)}" target="_blank" '
                f'rel="noopener noreferrer nofollow">Open the page</a> '
                f"<small>{escape(address)}</small></p>"
            )
        parts.append(
            "<p><small>The page opens in a new tab. Previewit checked it when it was "
            "submitted; it may have changed since. Comment on the whole page here.</small></p>"
        )
        parts.append("</div>")
        return "".join(parts)

    def check_selector(self, artifact: Artifact, selector: Mapping[str, str]) -> dict[str, str]:
        raise ArtifactError(
            "Comments cannot be pinned inside a web page; comment on the whole page."
        )


def _record(artifact: Artifact) -> dict[str, str]:
    try:
        data = json.loads(artifact.content.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items() if isinstance(v, str)}
