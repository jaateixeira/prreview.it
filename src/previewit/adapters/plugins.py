"""Finds installed plugins through the `previewit.plugins` entry-point group."""

from __future__ import annotations

from importlib.metadata import entry_points

from previewit.application.artifacts import ArtifactType

GROUP = "previewit.plugins"


def discover_artifact_types() -> list[ArtifactType]:
    """One instance of every installed plugin that implements the ArtifactType API."""
    found: list[ArtifactType] = []
    for entry in sorted(entry_points(group=GROUP), key=lambda e: e.name):
        plugin = entry.load()()
        if isinstance(plugin, ArtifactType):
            found.append(plugin)
    return found
