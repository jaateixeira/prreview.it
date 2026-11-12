"""The ArtifactType plugin API: how the core learns about kinds of content under review.

A plugin turns an upload into an immutable Artifact and knows how to show it. The core never
branches on a type key; it asks the registry for the plugin and calls it.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

from previewit.domain.calls import Artifact


class ArtifactError(ValueError):
    """The upload is not acceptable for this artifact type; the message is shown to the user."""


@dataclass(frozen=True)
class Upload:
    text: str | None = None  # from a text box
    content: bytes | None = None  # from a file
    filename: str | None = None


@runtime_checkable
class ArtifactType(Protocol):
    key: str
    label: str
    input_kind: Literal["text", "file"]  # which input the submission form shows
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
