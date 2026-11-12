"""Keep every test run away from a developer's real database and secrets."""

import os
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="previewit-tests-"))
os.environ["PREVIEWIT_DATABASE_URL"] = f"sqlite:///{_tmp / 'test.db'}"
os.environ["PREVIEWIT_SECRET_KEY"] = "test-only-secret"
os.environ["PREVIEWIT_BASE_URL"] = "http://testserver"
