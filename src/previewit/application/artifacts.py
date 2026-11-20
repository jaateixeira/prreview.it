"""The ArtifactType plugin API: how the core learns about kinds of content under review.

A plugin turns an upload into an immutable Artifact and knows how to show it. The core never
branches on a type key; it asks the registry for the plugin and calls it.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

from previewit.application.web_pages import PageChecker, PageReader
from previewit.domain.calls import Artifact


class ArtifactError(ValueError):
    """The upload is not acceptable for this artifact type; the message is shown to the user."""


@dataclass(frozen=True)
class Upload:
    text: str | None = None  # from a text box
    content: bytes | None = None  # from a file
    filename: str | None = None
    url: str | None = None  # the address of a web page (ADR 0022)


@runtime_checkable
class ArtifactType(Protocol):
    key: str
    label: str
    input_kind: Literal["text", "file", "url"]  # which input the submission form shows
    accept: str  # hint for the file picker, e.g. ".pdf"
    max_bytes: int
    annotation_kind: str  # "" when reviewers cannot pin comments to this type of content

    def ingest(self, upload: Upload) -> Artifact:
        """Validate and normalise. Raise ArtifactError with a user-readable reason."""
        ...

    def render_html(self, artifact: Artifact, raw_url: str) -> str:
        """Safe HTML that displays the artifact. `raw_url` serves its bytes."""
        ...

    def check_selector(self, artifact: Artifact, selector: Mapping[str, str]) -> dict[str, str]:
        """Validate where a comment is pinned (the selector the page sent) against this
        artifact and return it normalised. Raise ArtifactError if it does not fit."""
        ...


@runtime_checkable
class NamesItself(Protocol):
    """An artifact type whose content has a name to offer as a title (a web page's title)."""

    def title_of(self, artifact: Artifact) -> str: ...


@runtime_checkable
class ReadsText(Protocol):
    """An artifact type whose content an AI model can read as plain text (ADR 0025)."""

    def text_of(self, artifact: Artifact) -> str:
        """The words of the work. Raise ArtifactError, in words for the person, if they cannot
        be read (a scanned PDF, a page that is gone)."""
        ...


@dataclass(frozen=True)
class PluginServices:
    """What the core lends to plugins that need the world outside: given at startup by the
    composition root, so a plugin never imports an adapter."""

    pages: PageChecker
    reader: PageReader | None = None  # reads a page's text for AI reviews (ADR 0025)


@runtime_checkable
class UsesServices(Protocol):
    def connect(self, services: PluginServices) -> None: ...


def connect_plugins(plugins: Iterable[object], services: PluginServices) -> None:
    for plugin in plugins:
        if isinstance(plugin, UsesServices):
            plugin.connect(services)


class UnknownArtifactType(KeyError):
    pass


class ArtifactRegistry:
    def __init__(self, types: Iterable[ArtifactType] = ()) -> None:
        self._types: dict[str, ArtifactType] = {}
        for t in types:
            self.register(t)

    def register(self, artifact_type: ArtifactType) -> None:
        if artifact_type.key in self._types:
            raise ValueError(f"artifact type {artifact_type.key!r} is registered twice")
        self._types[artifact_type.key] = artifact_type

    def get(self, key: str) -> ArtifactType:
        try:
            return self._types[key]
        except KeyError:
            raise UnknownArtifactType(key) from None

    def all(self) -> list[ArtifactType]:
        return list(self._types.values())

    def for_input(self, input_kind: str) -> ArtifactType | None:
        """The first type that takes this kind of input ("url" for a web address)."""
        return next((t for t in self._types.values() if t.input_kind == input_kind), None)
