"""Configuration: an optional TOML file, overridden by PREVIEWIT_* environment variables.

See docs/auth/login-setup.md and previewit.example.toml.
"""

from __future__ import annotations

import logging
import secrets
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from previewit.domain.policy import DEFAULT_POLICY, VerificationPolicy, parse_actions

log = logging.getLogger("previewit.config")

DEFAULT_CONFIG_PATHS = (Path("previewit.toml"), Path("/etc/previewit/previewit.toml"))


class ConfigError(Exception):
    """The configuration is invalid; the message says what to fix."""


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
    verification_policy: VerificationPolicy = field(default=DEFAULT_POLICY)

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
            verification_policy=_policy(env),
        )


def _get(env: Mapping[str, str], name: str) -> str | None:
    return env.get(f"PREVIEWIT_{name}") or None


def _apple_key(env: Mapping[str, str]) -> str | None:
    inline = _get(env, "APPLE_PRIVATE_KEY")
    if inline:
        return inline
    path = _get(env, "APPLE_PRIVATE_KEY_FILE")
    return Path(path).read_text() if path else None


def _policy(env: Mapping[str, str]) -> VerificationPolicy:
    raw = env.get("PREVIEWIT_REQUIRE_VERIFIED_EMAIL_FOR")
    if raw is None:
        return DEFAULT_POLICY
    try:
        names = [n for n in raw.split(",") if n.strip()]
        return VerificationPolicy(parse_actions(names))
    except ValueError as e:
        raise ConfigError(f"PREVIEWIT_REQUIRE_VERIFIED_EMAIL_FOR: {e}") from None


# (section, key) -> environment variable name (without the PREVIEWIT_ prefix)
_KEYS: dict[tuple[str, str], str] = {
    ("server", "base_url"): "BASE_URL",
    ("server", "secret_key"): "SECRET_KEY",
    ("database", "url"): "DATABASE_URL",
    ("mail", "smtp_host"): "SMTP_HOST",
    ("mail", "smtp_port"): "SMTP_PORT",
    ("mail", "smtp_user"): "SMTP_USER",
    ("mail", "smtp_password"): "SMTP_PASSWORD",
    ("mail", "smtp_security"): "SMTP_SECURITY",
    ("mail", "from"): "MAIL_FROM",
    ("login.google", "client_id"): "GOOGLE_CLIENT_ID",
    ("login.google", "client_secret"): "GOOGLE_CLIENT_SECRET",
    ("login.apple", "client_id"): "APPLE_CLIENT_ID",
    ("login.apple", "team_id"): "APPLE_TEAM_ID",
    ("login.apple", "key_id"): "APPLE_KEY_ID",
    ("login.apple", "private_key"): "APPLE_PRIVATE_KEY",
    ("login.haka", "entity_id"): "HAKA_ENTITY_ID",
    ("login.haka", "cert_file"): "HAKA_CERT_FILE",
    ("login.haka", "key_file"): "HAKA_KEY_FILE",
    ("login.haka", "metadata_url"): "HAKA_METADATA_URL",
    ("login.haka", "metadata_cert"): "HAKA_METADATA_CERT",
    ("login.haka", "metadata_file"): "HAKA_METADATA_FILE",
    ("login.haka", "discovery_url"): "HAKA_DISCOVERY_URL",
    ("login.haka", "idp_entity_id"): "HAKA_IDP_ENTITY_ID",
}
# Secrets that may be read from a file instead: (section, "<key>_file") -> the key it fills.
_SECRET_FILES: dict[tuple[str, str], tuple[str, str]] = {
    ("server", "secret_key_file"): ("server", "secret_key"),
    ("login.apple", "private_key_file"): ("login.apple", "private_key"),
}
_PATH_KEYS = {"HAKA_CERT_FILE", "HAKA_KEY_FILE", "HAKA_METADATA_FILE", "HAKA_METADATA_CERT"}
_SECRET_KEYS = {
    "SECRET_KEY",
    "SMTP_PASSWORD",
    "GOOGLE_CLIENT_SECRET",
    "APPLE_PRIVATE_KEY",
}
_POLICY_KEY = ("policy", "require_verified_email_for")
_INT_KEYS = {"SMTP_PORT"}


def load_settings(
    env: Mapping[str, str], search: Sequence[Path] = DEFAULT_CONFIG_PATHS
) -> Settings:
    """Read the config file (if any), then let PREVIEWIT_* variables override it."""
    explicit = env.get("PREVIEWIT_CONFIG")
    path: Path | None = None
    if explicit:
        path = Path(explicit)
        if not path.is_file():
            raise ConfigError(f"PREVIEWIT_CONFIG points to {path}, which is not a file")
    else:
        path = next((p for p in search if p.is_file()), None)
    merged: dict[str, str] = {}
    if path is not None:
        merged.update(_read_file(path))
    merged.update({k: v for k, v in env.items() if k.startswith("PREVIEWIT_")})
    return Settings.from_env(merged)


def _read_file(path: Path) -> dict[str, str]:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as e:
        raise ConfigError(f"cannot read {path}: {e}") from None
    base = path.resolve().parent
    flat: dict[tuple[str, str], Any] = {}
    _flatten(data, "", flat)
    out: dict[str, str] = {}
    has_secret = False
    for (section, key), value in flat.items():
        where = f"{section}.{key}"
        if (section, key) == _POLICY_KEY:
            if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
                raise ConfigError(f"{path}: {where} must be a list of action names")
            try:
                parse_actions(value)
            except ValueError as e:
                raise ConfigError(f"{path}: {where}: {e}") from None
            out["PREVIEWIT_REQUIRE_VERIFIED_EMAIL_FOR"] = ",".join(value)
        elif (section, key) in _SECRET_FILES:
            target = _SECRET_FILES[(section, key)]
            if target in flat:
                both = f"{target[0]}.{target[1]}"
                raise ConfigError(f"{path}: set either {both} or {where}, not both")
            out[f"PREVIEWIT_{_KEYS[target]}"] = _read_secret(path, where, value, base)
            has_secret = True
        elif (section, key) in _KEYS:
            name = _KEYS[(section, key)]
            out[f"PREVIEWIT_{name}"] = _scalar(path, where, value, name, base)
            has_secret = has_secret or name in _SECRET_KEYS
        else:
            raise ConfigError(f"{path}: unknown setting {where}")
    if has_secret:
        _warn_if_open(path)
    return out


def _flatten(node: Mapping[str, Any], prefix: str, out: dict[tuple[str, str], Any]) -> None:
    for key, value in node.items():
        if isinstance(value, dict):
            name = f"{prefix}.{key}" if prefix else key
            if not any(sec == name or sec.startswith(name + ".") for sec, _ in _all_sections()):
                raise ConfigError(f"unknown section [{name}]")
            _flatten(value, name, out)
        elif not prefix:
            raise ConfigError(f"setting {key!r} must be inside a section")
        else:
            out[(prefix, key)] = value


def _all_sections() -> set[tuple[str, str]]:
    return set(_KEYS) | set(_SECRET_FILES) | {_POLICY_KEY}


def _scalar(path: Path, where: str, value: Any, name: str, base: Path) -> str:
    if name in _INT_KEYS:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ConfigError(f"{path}: {where} must be a number")
        return str(value)
    if not isinstance(value, str):
        raise ConfigError(f"{path}: {where} must be text")
    if name in _PATH_KEYS and not Path(value).is_absolute():
        return str(base / value)
    return value


def _read_secret(path: Path, where: str, value: Any, base: Path) -> str:
    if not isinstance(value, str):
        raise ConfigError(f"{path}: {where} must be a file path")
    file = Path(value)
    file = file if file.is_absolute() else base / file
    try:
        text = file.read_text(encoding="utf-8")
    except OSError as e:
        raise ConfigError(f"{path}: {where}: cannot read {file}: {e}") from None
    return text.strip() if "PRIVATE KEY" not in text else text


def _warn_if_open(path: Path) -> None:
    try:
        mode = path.stat().st_mode
    except OSError:
        return
    if mode & 0o044:  # group- or world-readable
        log.warning("%s holds secrets and is readable by others; run: chmod 600 %s", path, path)
