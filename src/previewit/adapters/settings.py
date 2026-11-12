"""Configuration read from the environment (see docs/auth/login-setup.md)."""

from __future__ import annotations

import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    secret_key: str
    base_url: str = "http://localhost:8000"
    database_url: str = "sqlite:///previewit.db"
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_security: str = "starttls"  # starttls | ssl | none
    mail_from: str | None = None
    google_client_id: str | None = None
    google_client_secret: str | None = None
    apple_client_id: str | None = None
    apple_team_id: str | None = None
    apple_key_id: str | None = None
    apple_private_key: str | None = None
    haka_entity_id: str | None = None
    haka_cert_file: str | None = None
    haka_key_file: str | None = None
    haka_metadata_url: str | None = None
    haka_metadata_cert: str | None = None
    haka_metadata_file: str | None = None
    haka_discovery_url: str | None = None
    haka_idp_entity_id: str | None = None

    @property
    def https(self) -> bool:
        return self.base_url.startswith("https://")

    @property
    def origin(self) -> str:
        return self.base_url.rstrip("/")

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> Settings:
        base_url = env.get("PREVIEWIT_BASE_URL", cls.base_url)
        secret = env.get("PREVIEWIT_SECRET_KEY")
        if not secret:
            if base_url.startswith("https://"):
                raise RuntimeError("PREVIEWIT_SECRET_KEY is required when the base URL is https")
            secret = secrets.token_hex(32)  # dev: sessions end when the process restarts
        return cls(
            secret_key=secret,
            base_url=base_url,
            database_url=env.get("PREVIEWIT_DATABASE_URL", cls.database_url),
            smtp_host=_get(env, "SMTP_HOST"),
            smtp_port=int(_get(env, "SMTP_PORT") or cls.smtp_port),
            smtp_user=_get(env, "SMTP_USER"),
            smtp_password=_get(env, "SMTP_PASSWORD"),
            smtp_security=_get(env, "SMTP_SECURITY") or cls.smtp_security,
            mail_from=_get(env, "MAIL_FROM"),
            google_client_id=_get(env, "GOOGLE_CLIENT_ID"),
            google_client_secret=_get(env, "GOOGLE_CLIENT_SECRET"),
            apple_client_id=_get(env, "APPLE_CLIENT_ID"),
            apple_team_id=_get(env, "APPLE_TEAM_ID"),
            apple_key_id=_get(env, "APPLE_KEY_ID"),
            apple_private_key=_apple_key(env),
            haka_entity_id=_get(env, "HAKA_ENTITY_ID"),
            haka_cert_file=_get(env, "HAKA_CERT_FILE"),
            haka_key_file=_get(env, "HAKA_KEY_FILE"),
            haka_metadata_url=_get(env, "HAKA_METADATA_URL"),
            haka_metadata_cert=_get(env, "HAKA_METADATA_CERT"),
            haka_metadata_file=_get(env, "HAKA_METADATA_FILE"),
            haka_discovery_url=_get(env, "HAKA_DISCOVERY_URL"),
            haka_idp_entity_id=_get(env, "HAKA_IDP_ENTITY_ID"),
        )


def _get(env: Mapping[str, str], name: str) -> str | None:
    return env.get(f"PREVIEWIT_{name}") or None


def _apple_key(env: Mapping[str, str]) -> str | None:
    inline = _get(env, "APPLE_PRIVATE_KEY")
    if inline:
        return inline
    path = _get(env, "APPLE_PRIVATE_KEY_FILE")
    return Path(path).read_text() if path else None
