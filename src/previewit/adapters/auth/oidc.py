"""OpenID Connect login (Google) on top of Authlib, plus helpers shared with Apple."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, Protocol

from authlib.integrations.starlette_client import OAuth
from loguru import logger
from starlette.requests import Request
from starlette.responses import Response

from previewit.adapters.auth.base import AuthFailed
from previewit.domain.identity import Email, ExternalClaims, InvalidEmail, Provider

GOOGLE_METADATA_URL = "https://accounts.google.com/.well-known/openid-configuration"


class OAuthApp(Protocol):
    """The part of an Authlib client we use (lets tests stub the network away)."""

    async def authorize_redirect(
        self, request: Request, redirect_uri: str, **params: Any
    ) -> Response: ...

    async def authorize_access_token(self, request: Request) -> Mapping[str, Any]: ...


def is_true(value: object) -> bool:
    """OIDC says boolean; Apple says "true"/"false"."""
    return value is True or (isinstance(value, str) and value.lower() == "true")


def read_email(userinfo: Mapping[str, Any]) -> Email | None:
    raw = userinfo.get("email")
    if not isinstance(raw, str):
        return None
    try:
        return Email(raw)
    except InvalidEmail:
        return None


def require_subject(userinfo: Mapping[str, Any]) -> str:
    subject = userinfo.get("sub")
    if not isinstance(subject, str) or not subject.strip():
        raise AuthFailed("provider returned no subject")
    return subject


def claims_from_google(userinfo: Mapping[str, Any]) -> ExternalClaims:
    email = read_email(userinfo)
    name = userinfo.get("name")
    return ExternalClaims(
        provider=Provider.GOOGLE,
        subject=require_subject(userinfo),
        email=email,
        email_verified=email is not None and is_true(userinfo.get("email_verified")),
        display_name=name if isinstance(name, str) else None,
    )


async def exchange(app: OAuthApp, request: Request) -> Mapping[str, Any]:
    """Run the code exchange and return the verified id_token claims, or raise AuthFailed."""
    try:
        token = await app.authorize_access_token(request)
    except Exception as error:  # any failure in the provider round trip is a failed login
        logger.warning("OIDC code exchange failed: {}", error)
        raise AuthFailed(str(error)) from error
    userinfo = token.get("userinfo")
    if not userinfo:
        raise AuthFailed("provider returned no id_token")
    return userinfo


class OidcProvider:
    def __init__(
        self,
        app: OAuthApp,
        map_claims: Callable[[Mapping[str, Any]], ExternalClaims],
        *,
        authorize_params: Mapping[str, str] | None = None,
    ) -> None:
        self._app = app
        self._map = map_claims
        self._params = dict(authorize_params or {})

    async def begin(self, request: Request, redirect_uri: str) -> Response:
        return await self._app.authorize_redirect(request, redirect_uri, **self._params)

    async def complete(self, request: Request) -> ExternalClaims:
        return self._map(await exchange(self._app, request))


def google_provider(client_id: str, client_secret: str) -> OidcProvider:
    oauth = OAuth()
    app = oauth.register(
        "google",
        client_id=client_id,
        client_secret=client_secret,
        server_metadata_url=GOOGLE_METADATA_URL,
        client_kwargs={"scope": "openid email profile"},
    )
    assert app is not None
    return OidcProvider(app, claims_from_google, authorize_params={"prompt": "select_account"})
