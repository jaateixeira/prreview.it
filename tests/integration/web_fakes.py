"""Test doubles and helpers for the login web tests."""

from __future__ import annotations

import re
import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import count

from fastapi.responses import RedirectResponse, Response
from fastapi.testclient import TestClient
from starlette.requests import Request

from previewit.adapters.auth.base import AuthFailed, ExternalProvider
from previewit.adapters.auth.passwords import Argon2Hasher
from previewit.adapters.persistence.memory import (
    InMemoryEmailTokenRepository,
    InMemoryUserRepository,
)
from previewit.adapters.settings import Settings
from previewit.adapters.web.app import build_app
from previewit.application.auth import AuthService
from previewit.application.verification import VerificationService
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


class Outbox:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []

    def send(self, to: str, subject: str, body: str) -> None:
        self.sent.append((to, subject, body))

    def last_link(self) -> str:
        match = re.search(r"https?://\S+/verify\?token=\S+", self.sent[-1][2])
        assert match
        return match.group(0)


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 11, 12, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


@dataclass
class Harness:
    client: TestClient
    auth: AuthService
    outbox: Outbox
    clock: Clock


def make_harness(
    providers: Mapping[Provider, ExternalProvider] | None = None,
    *,
    base_url: str = "http://testserver",
) -> Harness:
    ids = count(1)
    users = InMemoryUserRepository()
    auth = AuthService(
        users,
        Argon2Hasher(time_cost=1, memory_cost=8, parallelism=1),
        lambda: f"u{next(ids)}",
    )
    outbox, clock = Outbox(), Clock()
    verification = VerificationService(
        users, InMemoryEmailTokenRepository(), outbox, base_url, clock
    )
    settings = Settings(secret_key="test-secret", base_url=base_url)
    app = build_app(settings, auth, verification, dict(providers or {}))
    client = TestClient(app, base_url=base_url, follow_redirects=False)
    return Harness(client, auth, outbox, clock)


def make_client(
    providers: Mapping[Provider, ExternalProvider] | None = None,
    *,
    base_url: str = "http://testserver",
) -> tuple[TestClient, AuthService]:
    harness = make_harness(providers, base_url=base_url)
    return harness.client, harness.auth


def csrf_token(client: TestClient, path: str) -> str:
    html = client.get(path).text
    match = re.search(r'name="csrf" value="([^"]+)"', html)
    assert match, f"no csrf field on {path}"
    return match.group(1)
