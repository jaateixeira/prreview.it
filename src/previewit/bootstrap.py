"""Composition root: the only place that wires adapters to ports."""

from __future__ import annotations

from fastapi import FastAPI

from previewit.adapters.web.app import build_app


def create_app() -> FastAPI:
    return build_app()
