"""The catalogue of AI models (ADR 0025): a data file for the services' models, plus the free
models installed on Previewit's own Ollama server, looked up every few minutes."""

from __future__ import annotations

import threading
import time
import tomllib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import httpx
from loguru import logger

from previewit.domain.ai_models import InvalidModelCard, ModelCard

CATALOGUE = Path(__file__).with_name("models.toml")
LOCAL = "local"
APIS = {"anthropic", "openai"}
LOOKUP_SECONDS = 300.0
LOCAL_MAX_OUTPUT = 2_000
MAKERS = {  # who made an installed model, by the start of its name
    "qwen": "Alibaba Qwen",
    "llama": "Meta",
    "gemma": "Google",
    "mistral": "Mistral AI",
    "ministral": "Mistral AI",
    "phi": "Microsoft",
    "deepseek": "DeepSeek",
    "gpt-oss": "OpenAI",
    "granite": "IBM",
    "olmo": "Ai2",
    "smollm": "Hugging Face",
    "glm": "Z.ai",
}


class CatalogueError(Exception):
    """The catalogue file is wrong; the message says where."""


@dataclass(frozen=True)
class Service:
    """Who runs some of the models and takes the key."""

    key: str
    name: str
    api: str  # "anthropic" (Messages API) or "openai" (chat completions)
    url: str
    key_label: str
    key_url: str
    hosted_in: str
    hosting: str
    prices: str  # the page the prices come from
    max_tokens_field: str = "max_tokens"


def load_catalogue(path: Path = CATALOGUE) -> tuple[dict[str, Service], list[ModelCard]]:
    """The services and their models, in the file's order."""
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise CatalogueError(f"cannot read {path}: {error}") from None
    services: dict[str, Service] = {}
    for key, raw in (data.get("services") or {}).items():
        try:
            service = Service(key=key, **raw)
        except TypeError as error:
            raise CatalogueError(f"{path}: [services.{key}]: {error}") from None
        if service.api not in APIS or not service.url.startswith("https://"):
            raise CatalogueError(f"{path}: [services.{key}]: unknown api or not an https url")
        services[key] = service
    cards: list[ModelCard] = []
    for raw in data.get("models") or []:
        cards.append(_card(path, raw, services))
    keys = [c.key for c in cards]
    if len(set(keys)) != len(keys):
        raise CatalogueError(f"{path}: a model key is used twice")
    return services, cards


def _card(path: Path, raw: Mapping[str, Any], services: Mapping[str, Service]) -> ModelCard:
    where = f"{path}: model {raw.get('key', '?')}"
    service = services.get(str(raw.get("service", "")))
    if service is None:
        raise CatalogueError(f"{where}: unknown service")
    try:
        checked = raw.get("checked")
        return ModelCard(
            key=str(raw["key"]),
            name=str(raw["name"]),
            maker=str(raw["maker"]),
            service=service.key,
            service_name=service.name,
            api_model=str(raw["model"]),
            hosted_in=str(raw.get("hosted_in", service.hosted_in)),
            hosting=str(raw.get("hosting", service.hosting)),
            input_usd=Decimal(str(raw["input"])),
            output_usd=Decimal(str(raw["output"])),
            context_tokens=int(raw["context"]),
            max_output_tokens=int(raw["max_output"]),
            typical_output_tokens=int(raw["typical_output"]),
            tier=int(raw["tier"]),
            open_weights=bool(raw.get("open_weights", False)),
            key_label=service.key_label,
            key_url=service.key_url,
            checked=checked if isinstance(checked, date) else None,
            note=str(raw.get("note", "")),
        )
    except KeyError as missing:
        raise CatalogueError(f"{where}: {missing} is missing") from None
    except (InvalidModelCard, InvalidOperation, ValueError) as error:
        raise CatalogueError(f"{where}: {error}") from None


class LocalModels:
    """The models installed on Previewit's own Ollama server. Previewit pays for them: they
    are free for people. Looked up every few minutes; none while the server cannot be reached."""

    def __init__(
        self,
        url: str,
        *,
        place: str,
        country: str,
        context: int,
        only: tuple[str, ...] = (),
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.url = url.rstrip("/")
        self._place = place
        self._country = country
        self._context = context
        self._only = only
        self._transport = transport
        self._clock = clock
        self._lock = threading.Lock()
        self._found: tuple[float, list[ModelCard]] | None = None
        self._warned = False

    def cards(self) -> list[ModelCard]:
        with self._lock:
            if self._found is not None and self._clock() - self._found[0] < LOOKUP_SECONDS:
                return list(self._found[1])
        names = self._installed()  # outside the lock: a slow server must not hold up others
        cards = [self._card(name) for name in names]
        with self._lock:
            self._found = (self._clock(), cards)
        return list(cards)

    def _installed(self) -> list[str]:
        try:
            with httpx.Client(transport=self._transport, timeout=3.0) as client:
                response = client.get(f"{self.url}/api/tags")
                response.raise_for_status()
                names = [str(m["name"]) for m in response.json().get("models", [])]
        except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError) as error:
            if not self._warned:
                logger.warning("the Ollama server at {} cannot be reached: {}", self.url, error)
                self._warned = True
            return []
        self._warned = False
        names = [n for n in names if "embed" not in n.lower()]
        if self._only:
            return [n for n in self._only if n in names]
        return sorted(names)

    def _card(self, name: str) -> ModelCard:
        family = name.split(":", 1)[0].lower()
        maker = next((who for start, who in MAKERS.items() if family.startswith(start)), "")
        most = min(LOCAL_MAX_OUTPUT, self._context // 4)
        return ModelCard(
            key=f"{LOCAL}/{name}",
            name=name,
            maker=maker or "Open model",
            service=LOCAL,
            service_name="Previewit",
            api_model=name,
            hosted_in=self._country,
            hosting=f"Previewit's own server, {self._place}",
            input_usd=Decimal(0),
            output_usd=Decimal(0),
            context_tokens=self._context,
            max_output_tokens=most,
            typical_output_tokens=min(1_500, most),
            tier=1,
            open_weights=True,
            free=True,
        )


class Catalogue:
    """The ModelCatalog port: free models first, then the file's models."""

    def __init__(self, cards: list[ModelCard], local: LocalModels | None = None) -> None:
        self._cards = list(cards)
        self._local = local

    def cards(self) -> list[ModelCard]:
        return (self._local.cards() if self._local else []) + list(self._cards)
