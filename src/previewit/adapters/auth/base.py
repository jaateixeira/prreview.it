"""The port every external login provider (Google, Apple, HAKA) implements."""

from __future__ import annotations

from typing import Protocol

from starlette.requests import Request
from starlette.responses import Response

from previewit.domain.identity import ExternalClaims


class AuthFailed(Exception):
    """The provider login could not be completed (bad state, denied, invalid response)."""


class ExternalProvider(Protocol):
    async def begin(self, request: Request, redirect_uri: str) -> Response:
        """Start a login: store flow state in request.session and redirect/POST to the provider."""
        ...

    async def complete(self, request: Request) -> ExternalClaims:
        """Finish a login from the callback request; raise AuthFailed on any problem."""
        ...
