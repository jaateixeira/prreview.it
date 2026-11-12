import os
import socket
import threading
import time

import pytest
import uvicorn

import previewit.bootstrap as bootstrap
from previewit.bootstrap import create_app


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
    # The app checks the Origin header of form posts against its own base URL.
    os.environ["PREVIEWIT_BASE_URL"] = f"http://127.0.0.1:{port}"
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
