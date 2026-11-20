"""Asking a model for a review (ADR 0025), over plain HTTP: the Anthropic Messages API, the
OpenAI-style chat completions API (OpenAI, Google, Mistral, xAI, DeepSeek, Hugging Face) and
Ollama on Previewit's own server.

The person's key goes in one request header and nowhere else: never in a log line, an error
message or the database. Error messages are written here, for the person, and never repeat
what the service sent back, which might quote the key.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

import httpx

from previewit.adapters.ai.catalog import LOCAL, Service
from previewit.application.ai_reviews import AiAnswer, AiPrompt, AiServiceError
from previewit.domain.ai_models import CHARS_PER_TOKEN, ModelCard

ANTHROPIC_VERSION = "2023-06-01"
TIMEOUT_SECONDS = 300.0  # a long work and a thinking model take minutes
LOCAL_TIMEOUT_SECONDS = 1_200.0  # a small server without a GPU is slow
_THINKING = re.compile(r"^\s*<think>.*?</think>\s*", re.DOTALL)


class HttpAiWriter:
    def __init__(
        self,
        services: Mapping[str, Service],
        *,
        ollama_url: str | None,
        user_agent: str,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._services = dict(services)
        self._ollama_url = ollama_url.rstrip("/") if ollama_url else None
        self._user_agent = user_agent
        self._transport = transport

    def write(self, card: ModelCard, key: str, prompt: AiPrompt) -> AiAnswer:
        try:
            if card.service == LOCAL:
                return self._ollama(card, prompt)
            service = self._services.get(card.service)
            if service is None:
                raise AiServiceError("Previewit no longer reaches that model's service.")
            if service.api == "anthropic":
                return self._anthropic(service, card, key, prompt)
            return self._chat_completions(service, card, key, prompt)
        except httpx.TimeoutException:
            raise AiServiceError(
                f"{card.service_name} took too long to answer. Try again later, or choose a "
                "faster model."
            ) from None
        except httpx.HTTPError:
            raise AiServiceError(
                f"Previewit could not reach {card.service_name}. Try again later."
            ) from None

    # -- the three kinds of API -------------------------------------------------------------

    def _anthropic(self, service: Service, card: ModelCard, key: str, prompt: AiPrompt) -> AiAnswer:
        data = self._post(
            card,
            service.url,
            {"x-api-key": key, "anthropic-version": ANTHROPIC_VERSION},
            {
                "model": card.api_model,
                "max_tokens": prompt.max_output_tokens,
                "system": prompt.system,
                "messages": [{"role": "user", "content": prompt.user}],
            },
            TIMEOUT_SECONDS,
        )
        blocks = data.get("content")
        if not isinstance(blocks, list):
            raise _unreadable(card)
        text = "".join(
            str(b.get("text", ""))
            for b in blocks
            if isinstance(b, dict) and b.get("type") == "text"
        )
        usage = data.get("usage") or {}
        return _answer(prompt, text, usage.get("input_tokens"), usage.get("output_tokens"))

    def _chat_completions(
        self, service: Service, card: ModelCard, key: str, prompt: AiPrompt
    ) -> AiAnswer:
        data = self._post(
            card,
            service.url,
            {"Authorization": f"Bearer {key}"},
            {
                "model": card.api_model,
                "messages": [
                    {"role": "system", "content": prompt.system},
                    {"role": "user", "content": prompt.user},
                ],
                service.max_tokens_field: prompt.max_output_tokens,
            },
            TIMEOUT_SECONDS,
        )
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise _unreadable(card) from None
        if isinstance(content, list):  # some services send parts
            content = "".join(str(p.get("text", "")) for p in content if isinstance(p, dict))
        usage = data.get("usage") or {}
        return _answer(
            prompt, str(content or ""), usage.get("prompt_tokens"), usage.get("completion_tokens")
        )

    def _ollama(self, card: ModelCard, prompt: AiPrompt) -> AiAnswer:
        if self._ollama_url is None:
            raise AiServiceError("Previewit's own server for free models is not set up.")
        data = self._post(
            card,
            f"{self._ollama_url}/api/chat",
            {},
            {
                "model": card.api_model,
                "stream": False,
                "messages": [
                    {"role": "system", "content": prompt.system},
                    {"role": "user", "content": prompt.user},
                ],
                "options": {
                    "num_ctx": card.context_tokens,
                    "num_predict": prompt.max_output_tokens,
                },
            },
            LOCAL_TIMEOUT_SECONDS,
        )
        message = data.get("message")
        if not isinstance(message, dict):
            raise _unreadable(card)
        return _answer(
            prompt,
            str(message.get("content") or ""),
            data.get("prompt_eval_count"),
            data.get("eval_count"),
        )

    # -- one request ---------------------------------------------------------------------------

    def _post(
        self,
        card: ModelCard,
        url: str,
        headers: Mapping[str, str],
        body: Mapping[str, Any],
        timeout: float,
    ) -> dict[str, Any]:
        with httpx.Client(transport=self._transport, timeout=httpx.Timeout(timeout)) as client:
            response = client.post(
                url, json=body, headers={**headers, "User-Agent": self._user_agent}
            )
        status = response.status_code
        who = card.service_name
        if status in (401, 403):
            raise AiServiceError(
                f"{who} refused the key. Check that you copied all of it and that it may use "
                f"{card.name}."
            )
        if status == 402:
            raise AiServiceError(f"The {who} account behind the key has no credit left.")
        if status == 404:
            raise AiServiceError(f"{who} does not offer {card.name} under that name any more.")
        if status == 429:
            raise AiServiceError(
                f"{who} is busy, or the key has reached its limit. Try again later."
            )
        if status >= 500:
            raise AiServiceError(f"{who} has a problem right now (answer {status}). Try later.")
        if not 200 <= status < 300:
            raise AiServiceError(f"{who} turned the request down (answer {status}).")
        try:
            data = response.json()
        except ValueError:
            raise _unreadable(card) from None
        if not isinstance(data, dict):
            raise _unreadable(card)
        return data


def _answer(prompt: AiPrompt, text: str, read: object, written: object) -> AiAnswer:
    clean = _THINKING.sub("", text).strip()  # some open models show their thinking first
    input_tokens = read if isinstance(read, int) else len(prompt.system + prompt.user) // 4
    output_tokens = written if isinstance(written, int) else len(text) // CHARS_PER_TOKEN
    return AiAnswer(clean, input_tokens, output_tokens)


def _unreadable(card: ModelCard) -> AiServiceError:
    return AiServiceError(f"{card.service_name} sent an answer Previewit could not read.")
