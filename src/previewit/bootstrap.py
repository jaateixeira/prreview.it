"""Composition root: the only place that wires adapters to ports."""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version

from fastapi import FastAPI
from loguru import logger

from previewit.adapters.auth.passwords import Argon2Hasher
from previewit.adapters.auth.registry import build_providers
from previewit.adapters.cache import ValkeyCache, make_cache
from previewit.adapters.console import show_startup, startup_panel
from previewit.adapters.entitlements import UnlimitedEntitlements
from previewit.adapters.logs import configure_logging
from previewit.adapters.mail import LogMailer, SmtpMailer
from previewit.adapters.persistence.cached_users import DEFAULT_TTL_SECONDS, CachedUserRepository
from previewit.adapters.persistence.engine import make_engine
from previewit.adapters.persistence.migrate import upgrade
from previewit.adapters.persistence.sql import (
    SqlEmailTokenRepository,
    SqlTenancyRepository,
    SqlUserRepository,
)
from previewit.adapters.persistence.sql_calls import SqlCallRepository
from previewit.adapters.persistence.sql_reviews import SqlReviewRepository
from previewit.adapters.persistence.sql_rounds import SqlRoundRepository
from previewit.adapters.persistence.sql_rubrics import SqlRubricRepository
from previewit.adapters.plugins import (
    discover_allocation_strategies,
    discover_artifact_types,
    discover_criterion_types,
)
from previewit.adapters.settings import Settings, load_settings
from previewit.adapters.web.app import build_app
from previewit.application.allocation import StrategyRegistry
from previewit.application.artifacts import ArtifactRegistry
from previewit.application.auth import AuthService
from previewit.application.calls import CallsService
from previewit.application.criteria import CriterionRegistry
from previewit.application.invitations import InvitationsService
from previewit.application.ports import Mailer
from previewit.application.reviews import ReviewsService
from previewit.application.rounds import RoundsService
from previewit.application.rubrics import RubricsService
from previewit.application.tenancy import TenancyService
from previewit.application.verification import VerificationService


def create_app() -> FastAPI:
    settings = load_settings(os.environ)
    configure_logging(settings.log_level)
    cache = make_cache(settings.cache_url)
    if settings.cache_url is None and int(os.environ.get("WEB_CONCURRENCY", "1") or 1) > 1:
        logger.warning(
            "several workers without a [cache] url: each keeps its own cache, so changes can "
            "take up to {}s to show in other workers. Configure Valkey.",
            DEFAULT_TTL_SECONDS,
        )
    # Dev convenience: SQLite is migrated automatically. PostgreSQL is migrated explicitly.
    if settings.database_url.startswith("sqlite"):
        upgrade(settings.database_url)
    engine = make_engine(settings.database_url)
    users = CachedUserRepository(SqlUserRepository(engine), cache)
    auth = AuthService(
        users,
        Argon2Hasher(),
        lambda: uuid.uuid4().hex,
    )
    providers = build_providers(settings)
    mailer = build_mailer(settings)
    artifact_types = discover_artifact_types()
    verification = VerificationService(
        users,
        SqlEmailTokenRepository(engine),
        mailer,
        settings.base_url,
        lambda: datetime.now(UTC),
    )
    tenancy_repo = SqlTenancyRepository(engine)
    tenancy = TenancyService(
        tenancy_repo,
        users,
        lambda: uuid.uuid4().hex,
        lambda: datetime.now(UTC),
        policy=settings.verification_policy,
    )
    call_repo = SqlCallRepository(engine)
    calls = CallsService(
        call_repo,
        tenancy,
        tenancy_repo,
        users,
        ArtifactRegistry(artifact_types),
        UnlimitedEntitlements(),
        lambda: uuid.uuid4().hex,
        lambda: datetime.now(UTC),
        policy=settings.verification_policy,
    )
    criterion_types = CriterionRegistry(discover_criterion_types())
    rubric_repo = SqlRubricRepository(engine)
    rubrics = RubricsService(
        rubric_repo,
        call_repo,
        tenancy,
        criterion_types,
        lambda: uuid.uuid4().hex,
    )
    strategies = StrategyRegistry(discover_allocation_strategies())
    round_repo = SqlRoundRepository(engine)
    review_repo = SqlReviewRepository(engine)
    rounds = RoundsService(
        round_repo,
        review_repo,
        call_repo,
        tenancy,
        tenancy_repo,
        users,
        strategies,
        lambda: uuid.uuid4().hex,
        lambda: datetime.now(UTC),
    )
    invitations = InvitationsService(
        round_repo,
        call_repo,
        tenancy,
        tenancy_repo,
        users,
        UnlimitedEntitlements(),
        lambda: uuid.uuid4().hex,
        lambda: datetime.now(UTC),
        mailer=mailer,
        base_url=settings.base_url,
        policy=settings.verification_policy,
    )
    registry = ArtifactRegistry(artifact_types)
    reviews = ReviewsService(
        review_repo,
        round_repo,
        call_repo,
        rubric_repo,
        tenancy,
        tenancy_repo,
        users,
        criterion_types,
        registry,
        lambda: uuid.uuid4().hex,
        lambda: datetime.now(UTC),
    )
    mailer_mode = "SMTP" if isinstance(mailer, SmtpMailer) else "written to the log (development)"
    show_startup(
        startup_panel(
            settings,
            version=_version(),
            cache_kind="Valkey" if isinstance(cache, ValkeyCache) else "in-process",
            mail_mode=mailer_mode,
            providers=[p.value for p in providers],
            artifact_types=[t.key for t in registry.all()],
            log_level=settings.log_level,
        )
    )
    return build_app(
        settings,
        auth,
        verification,
        tenancy,
        calls,
        rubrics,
        rounds,
        reviews,
        invitations,
        providers,
    )


def _version() -> str:
    try:
        return version("previewit")
    except PackageNotFoundError:
        return "dev"


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
