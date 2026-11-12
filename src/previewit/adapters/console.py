"""What the operator sees on stdout when the server starts (rich)."""

from __future__ import annotations

from collections.abc import Iterable

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from previewit.adapters.settings import Settings


def _scheme(url: str) -> str:
    return url.split("://", 1)[0] if "://" in url else url


def startup_panel(
    settings: Settings,
    *,
    version: str,
    cache_kind: str,
    mail_mode: str,
    providers: Iterable[str],
    artifact_types: Iterable[str],
    log_level: str,
) -> Panel:
    """Never includes secrets: only URLs without credentials, and on/off facts."""
    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold cyan", justify="right")
    table.add_column()
    table.add_row("Address", settings.base_url)
    table.add_row("Database", _scheme(settings.database_url))
    table.add_row("Cache", cache_kind)
    table.add_row("Mail", mail_mode)
    table.add_row("Login", ", ".join(["password", *providers]))
    table.add_row("Artifact types", ", ".join(artifact_types) or "none")
    needs = sorted(a.value for a in settings.verification_policy.required_for)
    table.add_row("Verified email for", ", ".join(needs) or "nothing")
    table.add_row("Log level", log_level)
    return Panel(
        table, title=f"[bold]Previewit {version}[/bold]", border_style="cyan", expand=False
    )


def show_startup(panel: Panel, console: Console | None = None) -> None:
    (console or Console()).print(panel)
