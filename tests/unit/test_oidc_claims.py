import asyncio
import json
from collections.abc import Coroutine, Mapping
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from typing import Any, cast

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from joserfc import jwt
from joserfc.jwk import ECKey
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response

from previewit.adapters.auth.apple import (
    apple_client_secret,
    apple_name_hint,
    claims_from_apple,
)
from previewit.adapters.auth.base import AuthFailed
from previewit.adapters.auth.oidc import OidcProvider, claims_from_google
from previewit.domain.identity import Email, Provider

# --- Google claim mapping ----------------------------------------------------------


def test_google_verified_email():
    claims = claims_from_google(
        {"sub": "123", "email": "Ann@Gmail.com", "email_verified": True, "name": "Ann A"}
    )
    assert claims.provider is Provider.GOOGLE and claims.subject == "123"
    assert claims.email == Email("ann@gmail.com") and claims.email_verified
    assert claims.display_name == "Ann A"


def test_google_unverified_email_is_not_trusted():
    claims = claims_from_google({"sub": "1", "email": "a@x.fi", "email_verified": False})
    assert claims.email == Email("a@x.fi") and not claims.email_verified


@pytest.mark.parametrize("userinfo", [{}, {"sub": ""}, {"sub": "  "}])
def test_missing_subject_fails(userinfo):
    with pytest.raises(AuthFailed):
        claims_from_google(userinfo)


def test_garbage_email_is_dropped_not_fatal():
    claims = claims_from_google({"sub": "1", "email": "not an email", "email_verified": True})
    assert claims.email is None and not claims.email_verified


# --- Apple claim mapping -------------------------------------------------------------


def test_apple_sends_email_verified_as_a_string():
    claims = claims_from_apple({"sub": "00.abc", "email": "a@x.fi", "email_verified": "true"}, None)
    assert claims.provider is Provider.APPLE and claims.email_verified
    assert not claims_from_apple(
        {"sub": "1", "email": "a@x.fi", "email_verified": "false"}, None
    ).email_verified


def test_apple_name_comes_from_the_first_login_form_field_only():
    user_field = json.dumps({"name": {"firstName": "Ann", "lastName": "Apple"}})
    assert apple_name_hint(user_field) == "Ann Apple"
    assert apple_name_hint(None) is None
    assert apple_name_hint("{not json") is None
    assert apple_name_hint(json.dumps({"name": {}})) is None
    claims = claims_from_apple({"sub": "1"}, "Ann Apple")
    assert claims.display_name == "Ann Apple" and claims.email is None


# --- Apple client secret ---------------------------------------------------------------


def _pem_pair():
    private = ec.generate_private_key(ec.SECP256R1())
    pem = private.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    return pem, ECKey.import_key(pem)


def test_apple_client_secret_is_a_correctly_signed_es256_jwt():
    pem, key = _pem_pair()
    secret = apple_client_secret(
        team_id="TEAM123456",
        client_id="eu.example.web",
        key_id="KEY1234567",
        private_key_pem=pem,
        now=1_700_000_000,
    )
    token = jwt.decode(secret, key)
    assert token.header == {"alg": "ES256", "kid": "KEY1234567", "typ": "JWT"}
    assert token.claims == {
        "iss": "TEAM123456",
        "sub": "eu.example.web",
        "aud": "https://appleid.apple.com",
        "iat": 1_700_000_000,
        "exp": 1_700_000_000 + 300,
    }


def test_apple_private_key_may_be_given_with_escaped_newlines():
    pem, _ = _pem_pair()
    one_line = pem.strip().replace("\n", "\\n")
    assert apple_client_secret("T", "c", "K", one_line, now=1)


# --- generic OIDC provider ---------------------------------------------------------------


class StubApp:
    def __init__(self, token: Mapping[str, Any] | None = None, error: Exception | None = None):
        self.token: Mapping[str, Any] = token or {}
        self.error = error
        self.redirect: tuple[str, dict[str, Any]] | None = None

    async def authorize_redirect(
        self, request: Request, redirect_uri: str, **params: Any
    ) -> Response:
        self.redirect = (redirect_uri, params)
        return PlainTextResponse("redirected")

    async def authorize_access_token(self, request: Request) -> Mapping[str, Any]:
        if self.error:
            raise self.error
        return self.token


def run[T](coro: Coroutine[Any, Any, T]) -> T:
    """Run a coroutine on a fresh loop, even if another loop (Playwright's) is running here."""
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


def _request() -> Request:
    return cast(Request, SimpleNamespace())


def test_provider_begin_passes_redirect_uri_and_extra_params():
    app = StubApp()
    provider = OidcProvider(app, claims_from_google, authorize_params={"prompt": "select_account"})
    assert run(provider.begin(_request(), "https://h/cb")).body == b"redirected"
    assert app.redirect == ("https://h/cb", {"prompt": "select_account"})


def test_provider_complete_maps_userinfo():
    app = StubApp({"userinfo": {"sub": "9", "email": "a@x.fi", "email_verified": True}})
    claims = run(OidcProvider(app, claims_from_google).complete(_request()))
    assert claims.subject == "9"


@pytest.mark.parametrize(
    "app",
    [
        StubApp({"access_token": "x"}),  # no id_token, so no userinfo
        StubApp(error=RuntimeError("boom")),
        StubApp(error=ValueError("bad signature")),
    ],
)
def test_provider_complete_turns_every_failure_into_auth_failed(app):
    with pytest.raises(AuthFailed):
        run(OidcProvider(app, claims_from_google).complete(_request()))
