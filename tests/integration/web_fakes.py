"""Test doubles and helpers for the login web tests."""

from __future__ import annotations

import re
import secrets
from collections.abc import Mapping
from itertools import count

from fastapi.responses import RedirectResponse, Response
from fastapi.testclient import TestClient
from starlette.requests import Request

from previewit.adapters.auth.base import AuthFailed, ExternalProvider
from previewit.adapters.auth.passwords import Argon2Hasher
from previewit.adapters.persistence.memory import InMemoryUserRepository
from previewit.adapters.settings import Settings
from previewit.adapters.web.app import build_app
from previewit.application.auth import AuthService
from previewit.domain.identity import Email, ExternalClaims, Provider


class FakeProvider:
    """Behaves like an OIDC provider: round trip through the flow session, then claims."""

    def __init__(self, provider: Provider = Provider.GOOGLE) -> None:
        self.provider = provider
        self.claims = ExternalClaims(provider, "sub-1", Email("ann@x.fi"), True, "Ann")

    async def begin(self, request: Request, redirect_uri: str) -> Response:
        state = secrets.token_urlsafe(8)
        request.session["fake_state"] = state
        return RedirectResponse(f"{redirect_uri}?state={state}", status_code=303)

    async def complete(self, request: Request) -> ExternalClaims:
        expected = request.session.pop("fake_state", None)
        if expected is None or request.query_params.get("state") != expected:
            raise AuthFailed("state mismatch")
        return self.claims


def make_client(
    providers: Mapping[Provider, ExternalProvider] | None = None,
    *,
    base_url: str = "http://testserver",
) -> tuple[TestClient, AuthService]:
    ids = count(1)
    auth = AuthService(
        InMemoryUserRepository(),
        Argon2Hasher(time_cost=1, memory_cost=8, parallelism=1),
        lambda: f"u{next(ids)}",
    )
    settings = Settings(secret_key="test-secret", base_url=base_url)
    app = build_app(settings, auth, dict(providers or {}))
    return TestClient(app, base_url=base_url, follow_redirects=False), auth


def csrf_token(client: TestClient, path: str) -> str:
    html = client.get(path).text
    match = re.search(r'name="csrf" value="([^"]+)"', html)
    assert match, f"no csrf field on {path}"
    return match.group(1)
