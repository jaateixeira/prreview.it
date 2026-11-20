import os
import socket
import threading
import time

import httpx
import pytest
import uvicorn
from tests.unit.test_webpage_plugin import FakePageChecker

import previewit.bootstrap as bootstrap
from previewit.adapters.ai.catalog import Catalogue, LocalModels, Service, load_catalogue
from previewit.adapters.settings import Settings
from previewit.application.ai_reviews import AiAnswer, AiPrompt
from previewit.application.web_pages import PageCheck
from previewit.bootstrap import create_app
from previewit.domain.ai_models import ModelCard


class Outbox:
    """Captures verification mails so scenarios can open the link."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []

    def send(self, to: str, subject: str, body: str) -> None:
        self.sent.append((to, subject, body))

    def link_for(self, email: str) -> str:
        body = next(b for to, _, b in reversed(self.sent) if to == email)
        return next(w for w in body.split() if "/verify?token=" in w)


OUTBOX = Outbox()

# Web pages the scenarios review (ADR 0022): the test server never leaves this machine.
PAGES = FakePageChecker(
    {
        "https://example.org/portfolio": PageCheck(
            "https://example.org/portfolio",
            "https://example.org/portfolio",
            "Maya's design portfolio",
            "Six projects from 2026.",
            "Maya Maker",
            "text/html",
        ),
        "https://example.org/private": "The page asks for a login. Reviewers need a page anyone "
        "can open: use a public address.",
    }
)


class Writer:
    """Plays every AI model (ADR 0025): answers at once, never leaves this machine."""

    def __init__(self) -> None:
        self.asked: list[tuple[str, str]] = []

    def write(self, card: ModelCard, key: str, prompt: AiPrompt) -> AiAnswer:
        self.asked.append((card.key, key))
        return AiAnswer(
            "Summary\nA thoughtful essay.\n\nWhat to improve\nGive one more example.", 900, 40
        )


WRITER = Writer()


def _catalogue(settings: Settings) -> tuple[dict[str, Service], Catalogue]:
    """The real catalogue, plus one free model on a pretend Ollama server."""
    services, cards = load_catalogue()
    ollama = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"models": [{"name": "qwen3:8b"}]})
    )
    local = LocalModels(
        "http://ollama.test:11434", place="Finland", country="FI", context=8192, transport=ollama
    )
    return services, Catalogue(cards, local)


@pytest.fixture(scope="session")
def writer() -> Writer:
    return WRITER


@pytest.fixture(scope="session")
def outbox() -> Outbox:
    return OUTBOX


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def base_url():
    port = _free_port()
    bootstrap.build_mailer = lambda _settings: OUTBOX  # type: ignore[assignment]
    bootstrap.build_page_checker = lambda _settings: PAGES  # type: ignore[assignment]
    bootstrap.build_ai_catalogue = _catalogue  # type: ignore[assignment]
    bootstrap.build_ai_writer = lambda _settings, _services: WRITER  # type: ignore[assignment]
    # The app checks the Origin header of form posts against its own base URL.
    os.environ["PREVIEWIT_BASE_URL"] = f"http://127.0.0.1:{port}"
    # The same server under a second name, to show that an alias leads to the main address.
    os.environ["PREVIEWIT_ALIASES"] = f"http://localhost:{port}"
    server = uvicorn.Server(
        uvicorn.Config(create_app(), host="127.0.0.1", port=port, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    else:
        pytest.fail("test server did not start within 5 seconds")
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)
