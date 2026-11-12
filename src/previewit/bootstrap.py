"""Composition root: the only place that wires adapters to ports."""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime

from fastapi import FastAPI
from sqlalchemy import create_engine

from previewit.adapters.auth.passwords import Argon2Hasher
from previewit.adapters.auth.registry import build_providers
from previewit.adapters.mail import LogMailer, SmtpMailer
from previewit.adapters.persistence.migrate import upgrade
from previewit.adapters.persistence.sql import SqlEmailTokenRepository, SqlUserRepository
from previewit.adapters.settings import Settings
from previewit.adapters.web.app import build_app
from previewit.application.auth import AuthService
from previewit.application.ports import Mailer
from previewit.application.verification import VerificationService


def create_app() -> FastAPI:
    settings = Settings.from_env(os.environ)
    # Dev convenience: SQLite is migrated automatically. PostgreSQL is migrated explicitly.
    if settings.database_url.startswith("sqlite"):
        upgrade(settings.database_url)
    engine = create_engine(settings.database_url)
    users = SqlUserRepository(engine)
    auth = AuthService(
        users,
        Argon2Hasher(),
        lambda: uuid.uuid4().hex,
    )
    providers = build_providers(settings)
    verification = VerificationService(
        users,
        SqlEmailTokenRepository(engine),
        build_mailer(settings),
        settings.base_url,
        lambda: datetime.now(UTC),
    )
    return build_app(settings, auth, verification, providers)


def build_mailer(settings: Settings) -> Mailer:
    if settings.smtp_host:
        if not settings.mail_from:
            raise RuntimeError("PREVIEWIT_MAIL_FROM is required when PREVIEWIT_SMTP_HOST is set")
        return SmtpMailer(
            settings.smtp_host,
            settings.smtp_port,
            settings.smtp_user,
            settings.smtp_password,
            settings.mail_from,
            settings.smtp_security,
        )
    if settings.https:
        raise RuntimeError("Set PREVIEWIT_SMTP_HOST: verification emails need a mail server")
    return LogMailer()  # development: the link appears in the server log
