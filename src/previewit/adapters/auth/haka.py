"""HAKA (Finnish higher-education identity federation, run by CSC) via SAML 2.0.

The pure claim mapping needs nothing but the standard library. The SAML plumbing
needs the optional `saml` extra (pysaml2) and the `xmlsec1` binary, and is imported
lazily so the rest of the application runs without them.
"""

from __future__ import annotations

import asyncio
import shutil
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

from loguru import logger
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

from previewit.adapters.auth.base import AuthFailed
from previewit.domain.identity import Email, ExternalClaims, InvalidEmail, Provider

PERSISTENT = "urn:oasis:names:tc:SAML:2.0:nameid-format:persistent"
_SAML_IDS = "saml_request_ids"


def _first(ava: Mapping[str, Sequence[str]], key: str) -> str | None:
    for value in ava.get(key, ()):
        if value and value.strip():
            return value.strip()
    return None


def claims_from_haka(
    idp_entity_id: str,
    ava: Mapping[str, Sequence[str]],
    name_id: str | None,
    name_id_format: str | None,
) -> ExternalClaims:
    """Map SAML attributes to claims.

    The subject is scoped by the IdP, because identifiers are only unique per issuer.
    A mail address is only vouched for when it belongs to the user's home organisation.
    """
    identifier = _first(ava, "eduPersonUniqueId")
    if identifier is None and name_id and name_id_format == PERSISTENT:
        identifier = name_id.strip() or None
    if identifier is None:
        identifier = _first(ava, "eduPersonPrincipalName")
    if identifier is None:
        raise AuthFailed("the identity provider released no stable identifier")

    email: Email | None = None
    raw_mail = _first(ava, "mail")
    if raw_mail:
        try:
            email = Email(raw_mail)
        except InvalidEmail:
            email = None
    home = (_first(ava, "schacHomeOrganization") or "").lower()
    verified = (
        email is not None
        and bool(home)
        and (email.domain == home or email.domain.endswith("." + home))
    )
    return ExternalClaims(
        provider=Provider.HAKA,
        subject=f"{idp_entity_id}!{identifier}",
        email=email,
        email_verified=verified,
        display_name=_first(ava, "displayName") or _first(ava, "cn"),
    )


@dataclass(frozen=True)
class HakaConfig:
    sp_entity_id: str
    acs_url: str
    cert_file: str
    key_file: str
    metadata_url: str | None = None
    metadata_cert: str | None = None  # certificate that signs the federation metadata
    metadata_file: str | None = None  # local metadata (the Haka test IdP, or tests)
    discovery_url: str | None = None
    idp_entity_id: str | None = None  # skip discovery and always use this IdP


class HakaProvider:
    """SAML Service Provider. pysaml2 is blocking, so it runs in a worker thread."""

    def __init__(self, config: HakaConfig) -> None:
        self._config = config
        self._client: Any = None
        self._lock = threading.Lock()

    # -- lazy setup (loading federation metadata is a network fetch) -----------------

    def _sp_config(self) -> Any:
        from saml2 import BINDING_HTTP_POST
        from saml2.config import SPConfig

        cfg = self._config
        metadata: dict[str, list[Any]] = {}
        if cfg.metadata_file:
            metadata["local"] = [cfg.metadata_file]
        if cfg.metadata_url:
            metadata["remote"] = [{"url": cfg.metadata_url, "cert": cfg.metadata_cert}]
        conf = SPConfig()
        conf.load(
            {
                "entityid": cfg.sp_entity_id,
                "xmlsec_binary": shutil.which("xmlsec1"),
                "key_file": cfg.key_file,
                "cert_file": cfg.cert_file,
                "metadata": metadata,
                "service": {
                    "sp": {
                        "endpoints": {
                            "assertion_consumer_service": [(cfg.acs_url, BINDING_HTTP_POST)]
                        },
                        "allow_unsolicited": False,
                        "authn_requests_signed": False,
                        "want_assertions_signed": True,
                        "want_response_signed": False,
                    }
                },
            }
        )
        return conf

    def _get_client(self) -> Any:
        from saml2.client import Saml2Client

        with self._lock:
            if self._client is None:
                self._client = Saml2Client(config=self._sp_config())
            return self._client

    # -- ExternalProvider ------------------------------------------------------------

    async def begin(self, request: Request, redirect_uri: str) -> Response:
        idp = self._config.idp_entity_id or request.query_params.get("entityID")
        if not idp:
            if not self._config.discovery_url:
                raise AuthFailed("no identity provider configured")
            # The discovery service sends the user back here with ?entityID=<chosen IdP>.
            query = urlencode(
                {
                    "entityID": self._config.sp_entity_id,
                    "return": str(request.url.remove_query_params("entityID")),
                }
            )
            return RedirectResponse(f"{self._config.discovery_url}?{query}", status_code=303)
        try:
            location, request_id = await asyncio.to_thread(self._authn_request, idp)
        except Exception as error:
            logger.warning("could not start HAKA login: {}", error)
            raise AuthFailed(str(error)) from error
        ids = list(request.session.get(_SAML_IDS, []))
        request.session[_SAML_IDS] = [*ids[-4:], request_id]
        return RedirectResponse(location, status_code=303)

    def _authn_request(self, idp: str) -> tuple[str, str]:
        from saml2 import BINDING_HTTP_REDIRECT

        client = self._get_client()
        request_id, info = client.prepare_for_authenticate(
            entityid=idp, binding=BINDING_HTTP_REDIRECT
        )
        headers = dict(info["headers"])
        return headers["Location"], request_id

    async def complete(self, request: Request) -> ExternalClaims:
        form = await request.form()
        saml_response = form.get("SAMLResponse")
        if not isinstance(saml_response, str):
            raise AuthFailed("no SAML response")
        outstanding = {rid: "/" for rid in request.session.get(_SAML_IDS, [])}
        try:
            claims, used = await asyncio.to_thread(self._parse, saml_response, outstanding)
        except AuthFailed:
            raise
        except Exception as error:
            logger.warning("HAKA response rejected: {}", error)
            raise AuthFailed(str(error)) from error
        request.session[_SAML_IDS] = [i for i in request.session.get(_SAML_IDS, []) if i != used]
        return claims

    def _parse(self, saml_response: str, outstanding: dict[str, str]) -> tuple[ExternalClaims, str]:
        from saml2 import BINDING_HTTP_POST

        client = self._get_client()
        response = client.parse_authn_request_response(
            saml_response, BINDING_HTTP_POST, outstanding=outstanding
        )
        if response is None:
            raise AuthFailed("invalid SAML response")
        name_id = response.name_id
        claims = claims_from_haka(
            str(response.issuer()),
            {k: [str(v) for v in vs] for k, vs in (response.get_identity() or {}).items()},
            name_id.text if name_id is not None else None,
            name_id.format if name_id is not None else None,
        )
        return claims, str(response.in_response_to)

    def metadata_xml(self) -> bytes:
        """Our SP metadata, to register the service with the federation."""
        from saml2.metadata import create_metadata_string

        xml = create_metadata_string(None, config=self._sp_config(), sign=False)
        return xml.encode() if isinstance(xml, str) else xml
