"""Composition root: the only place that wires adapters to ports."""

from __future__ import annotations

import os
import uuid

from fastapi import FastAPI
from sqlalchemy import create_engine

from previewit.adapters.auth.passwords import Argon2Hasher
from previewit.adapters.auth.registry import build_providers
from previewit.adapters.persistence.migrate import upgrade
from previewit.adapters.persistence.sql import SqlUserRepository
from previewit.adapters.settings import Settings
from previewit.adapters.web.app import build_app
from previewit.application.auth import AuthService


def create_app() -> FastAPI:
    settings = Settings.from_env(os.environ)
    # Dev convenience: SQLite is migrated automatically. PostgreSQL is migrated explicitly.
    if settings.database_url.startswith("sqlite"):
        upgrade(settings.database_url)
    auth = AuthService(
        SqlUserRepository(create_engine(settings.database_url)),
        Argon2Hasher(),
        lambda: uuid.uuid4().hex,
    )
    providers = build_providers(settings)
    return build_app(settings, auth, providers)
