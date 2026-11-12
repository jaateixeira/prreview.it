"""Keep every test run away from a developer's real database and secrets."""

import os
import tempfile
from pathlib import Path

import pytest

_tmp = Path(tempfile.mkdtemp(prefix="previewit-tests-"))
os.environ["PREVIEWIT_DATABASE_URL"] = f"sqlite:///{_tmp / 'test.db'}"
os.environ["PREVIEWIT_SECRET_KEY"] = "test-only-secret"
os.environ["PREVIEWIT_BASE_URL"] = "http://testserver"


@pytest.fixture
def logged():
    """Messages written through loguru during a test, as one string."""
    from loguru import logger

    messages: list[str] = []
    sink = logger.add(lambda m: messages.append(str(m)), level="TRACE", format="{level} {message}")

    class Captured:
        @property
        def text(self) -> str:
            return "".join(messages)

        def clear(self) -> None:
            messages.clear()

    yield Captured()
    logger.remove(sink)
