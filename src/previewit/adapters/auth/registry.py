"""Turn settings into the set of enabled login providers (checked at startup)."""

from __future__ import annotations

import importlib.util
import shutil
from collections.abc import Mapping

from previewit.adapters.auth.apple import apple_provider
from previewit.adapters.auth.base import ExternalProvider
from previewit.adapters.auth.haka import HakaConfig, HakaProvider
from previewit.adapters.auth.oidc import google_provider
from previewit.adapters.settings import Settings
from previewit.domain.identity import Provider


class ConfigurationError(Exception):
    """A provider is partly configured, or needs something that is not installed."""


def _complete(group: str, values: Mapping[str, str | None]) -> bool:
    """True if all set, False if none set; raise when only some are."""
    present = [name for name, value in values.items() if value]
    if not present:
        return False
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise ConfigurationError(
            f"{group} login is partly configured; missing {', '.join(missing)}"
        )
    return True


def build_providers(settings: Settings) -> dict[Provider, ExternalProvider]:
    providers: dict[Provider, ExternalProvider] = {}

    if _complete(
        "Google",
        {
            "PREVIEWIT_GOOGLE_CLIENT_ID": settings.google_client_id,
            "PREVIEWIT_GOOGLE_CLIENT_SECRET": settings.google_client_secret,
        },
    ):
        assert settings.google_client_id and settings.google_client_secret
        providers[Provider.GOOGLE] = google_provider(
            settings.google_client_id, settings.google_client_secret
        )

    if _complete(
        "Apple",
        {
            "PREVIEWIT_APPLE_CLIENT_ID": settings.apple_client_id,
            "PREVIEWIT_APPLE_TEAM_ID": settings.apple_team_id,
            "PREVIEWIT_APPLE_KEY_ID": settings.apple_key_id,
            "PREVIEWIT_APPLE_PRIVATE_KEY": settings.apple_private_key,
        },
    ):
        assert settings.apple_client_id and settings.apple_team_id
        assert settings.apple_key_id and settings.apple_private_key
        providers[Provider.APPLE] = apple_provider(
            settings.apple_client_id,
            settings.apple_team_id,
            settings.apple_key_id,
            settings.apple_private_key,
        )

    if _complete(
        "HAKA",
        {
            "PREVIEWIT_HAKA_ENTITY_ID": settings.haka_entity_id,
            "PREVIEWIT_HAKA_CERT_FILE": settings.haka_cert_file,
            "PREVIEWIT_HAKA_KEY_FILE": settings.haka_key_file,
        },
    ):
        providers[Provider.HAKA] = _haka(settings)
    elif any(
        (settings.haka_metadata_url, settings.haka_metadata_file, settings.haka_discovery_url)
    ):
        _complete(
            "HAKA",
            {
                "PREVIEWIT_HAKA_ENTITY_ID": settings.haka_entity_id,
                "PREVIEWIT_HAKA_CERT_FILE": settings.haka_cert_file,
                "PREVIEWIT_HAKA_KEY_FILE": settings.haka_key_file,
                "PREVIEWIT_HAKA_METADATA_URL": settings.haka_metadata_url,
            },
        )
    return providers


def _haka(settings: Settings) -> HakaProvider:
    assert settings.haka_entity_id and settings.haka_cert_file and settings.haka_key_file
    if not (settings.haka_metadata_url or settings.haka_metadata_file):
        raise ConfigurationError(
            "HAKA login needs PREVIEWIT_HAKA_METADATA_URL or PREVIEWIT_HAKA_METADATA_FILE"
        )
    if settings.haka_metadata_url and not settings.haka_metadata_cert:
        raise ConfigurationError(
            "HAKA metadata fetched from a URL must be verified: set PREVIEWIT_HAKA_METADATA_CERT"
        )
    if not (settings.haka_discovery_url or settings.haka_idp_entity_id):
        raise ConfigurationError(
            "HAKA login needs PREVIEWIT_HAKA_DISCOVERY_URL or PREVIEWIT_HAKA_IDP_ENTITY_ID"
        )
    if importlib.util.find_spec("saml2") is None or shutil.which("xmlsec1") is None:
        raise ConfigurationError(
            "HAKA login needs the 'saml' extra (uv sync --extra saml) and the xmlsec1 package"
        )
    return HakaProvider(
        HakaConfig(
            sp_entity_id=settings.haka_entity_id,
            acs_url=f"{settings.origin}/auth/haka/callback",
            cert_file=settings.haka_cert_file,
            key_file=settings.haka_key_file,
            metadata_url=settings.haka_metadata_url,
            metadata_cert=settings.haka_metadata_cert,
            metadata_file=settings.haka_metadata_file,
            discovery_url=settings.haka_discovery_url,
            idp_entity_id=settings.haka_idp_entity_id,
        )
    )
