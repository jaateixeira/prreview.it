"""Sign in with Apple (OIDC with a signed-JWT client secret and form_post callback)."""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping
from typing import Any

from authlib.integrations.starlette_client import OAuth
from joserfc import jwt
from joserfc.jwk import ECKey
from starlette.requests import Request
from starlette.responses import Response

from previewit.adapters.auth.base import AuthFailed
from previewit.adapters.auth.oidc import (
    OAuthApp,
    exchange,
    is_true,
    read_email,
    require_subject,
)
from previewit.domain.identity import ExternalClaims, Provider

APPLE_METADATA_URL = "https://appleid.apple.com/.well-known/openid-configuration"
APPLE_AUDIENCE = "https://appleid.apple.com"
SECRET_LIFETIME_SECONDS = 300  # only needs to outlive one token request


def apple_client_secret(
    team_id: str, client_id: str, key_id: str, private_key_pem: str, *, now: int | None = None
) -> str:
    """Apple's "client secret" is a short-lived ES256 JWT signed with the developer key."""
    issued = int(time.time()) if now is None else now
    key = ECKey.import_key(private_key_pem.replace("\\n", "\n"))
    claims = {
        "iss": team_id,
        "sub": client_id,
        "aud": APPLE_AUDIENCE,
        "iat": issued,
        "exp": issued + SECRET_LIFETIME_SECONDS,
    }
    return jwt.encode({"alg": "ES256", "kid": key_id, "typ": "JWT"}, claims, key)


def apple_name_hint(user_field: str | None) -> str | None:
    """Apple sends the name only on the very first authorisation, as JSON in a form field."""
    if not user_field:
        return None
    try:
        name = json.loads(user_field).get("name") or {}
        parts = [name.get("firstName"), name.get("lastName")]
    except (ValueError, AttributeError):
        return None
    full = " ".join(p for p in parts if isinstance(p, str) and p.strip())
    return full or None


def claims_from_apple(userinfo: Mapping[str, Any], name_hint: str | None) -> ExternalClaims:
    email = read_email(userinfo)
    return ExternalClaims(
        provider=Provider.APPLE,
        subject=require_subject(userinfo),
        email=email,
        email_verified=email is not None and is_true(userinfo.get("email_verified")),
        display_name=name_hint,
    )


class AppleProvider:
    def __init__(self, app: OAuthApp, make_secret: Callable[[], str]) -> None:
        self._app = app
        self._make_secret = make_secret

    async def begin(self, request: Request, redirect_uri: str) -> Response:
        # name/email scopes force Apple to answer with a cross-site form POST.
        return await self._app.authorize_redirect(request, redirect_uri, response_mode="form_post")

    async def complete(self, request: Request) -> ExternalClaims:
        hint = None
        if request.method == "POST":
            user_field = (await request.form()).get("user")
            hint = apple_name_hint(user_field if isinstance(user_field, str) else None)
        try:
            # Authlib reads client_secret from the app, so refresh it before every exchange.
            self._app.client_secret = self._make_secret()  # type: ignore[attr-defined]
        except Exception as error:  # a bad private key is a configuration problem
            raise AuthFailed("could not sign the Apple client secret") from error
        return claims_from_apple(await exchange(self._app, request), hint)


def apple_provider(
    client_id: str, team_id: str, key_id: str, private_key_pem: str
) -> AppleProvider:
    oauth = OAuth()
    app = oauth.register(
        "apple",
        client_id=client_id,
        client_secret=apple_client_secret(team_id, client_id, key_id, private_key_pem),
        server_metadata_url=APPLE_METADATA_URL,
        client_kwargs={"scope": "openid name email"},
    )
    assert app is not None
    return AppleProvider(
        app, lambda: apple_client_secret(team_id, client_id, key_id, private_key_pem)
    )
