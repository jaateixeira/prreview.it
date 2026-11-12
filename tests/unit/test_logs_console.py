import logging

import pytest
from loguru import logger
from rich.console import Console

from previewit.adapters.console import startup_panel
from previewit.adapters.logs import configure_logging
from previewit.adapters.settings import Settings
from previewit.domain.policy import Action, VerificationPolicy


def test_the_level_filters_and_standard_logging_is_captured():
    configure_logging("WARNING")
    seen: list[str] = []
    sink = logger.add(lambda m: seen.append(str(m)), level="TRACE", format="{message}")
    try:
        logger.info("quiet-info")  # below the configured sink level, but our probe sees it
        logging.getLogger("uvicorn.error").error("from-stdlib")
    finally:
        logger.remove(sink)
    assert any("from-stdlib" in m for m in seen)  # standard logging is routed through loguru


def test_the_configured_level_applies_to_the_stderr_sink(capfd):
    configure_logging("WARNING")
    logger.info("quiet-info")
    logger.warning("loud-warning")
    configure_logging("TRACE")
    logger.trace("very-detailed")
    err = capfd.readouterr().err
    assert "quiet-info" not in err and "loud-warning" in err and "very-detailed" in err


def test_an_unknown_level_is_refused():
    with pytest.raises(ValueError, match="TRACE"):
        configure_logging("LOUD")


def test_the_startup_panel_shows_the_setup_but_no_secrets():
    settings = Settings(
        secret_key="TOPSECRET",
        base_url="https://prreview.example",
        database_url="postgresql+psycopg://user:dbpassword@db/previewit",
        smtp_password="smtppassword",
        cache_url="valkey://:cachepassword@cache/0",
        verification_policy=VerificationPolicy(frozenset({Action.REVIEW})),
    )
    panel = startup_panel(
        settings, version="1.2.3", cache_kind="Valkey", mail_mode="SMTP",
        providers=["google"], artifact_types=["pdf", "text"], log_level="INFO",
    )  # fmt: skip
    console = Console(record=True, width=100, force_terminal=False)
    console.print(panel)
    out = console.export_text()
    for expected in ("Previewit 1.2.3", "prreview.example", "postgresql", "Valkey", "review"):
        assert expected in out
    for secret in ("TOPSECRET", "dbpassword", "smtppassword", "cachepassword"):
        assert secret not in out
