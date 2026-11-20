"""Previewit's own keys for the model services (ADR 0026): used only for AI reviews paid with
credit. They live in a file of their own, readable by the service account only:

    anthropic = "sk-ant-..."
    openai = "sk-..."
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from loguru import logger


class KeysFileError(Exception):
    pass


def load_house_keys(path: str | None, services: set[str]) -> dict[str, str]:
    if not path:
        return {}
    file = Path(path)
    try:
        data = tomllib.loads(file.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise KeysFileError(f"cannot read the AI keys file {file}: {error}") from None
    if file.stat().st_mode & 0o044:
        logger.warning("{} holds keys and is readable by others; run: chmod 600 {}", file, file)
    keys: dict[str, str] = {}
    for service, key in data.items():
        if service not in services:
            raise KeysFileError(f"{file}: no model service is called {service!r}")
        if not isinstance(key, str) or not key.strip():
            raise KeysFileError(f"{file}: the key for {service} must be text")
        keys[service] = key.strip()
    return keys
