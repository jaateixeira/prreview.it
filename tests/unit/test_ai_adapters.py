"""The catalogue of AI models, the services that write the reviews, and the job queue
(ADR 0025). No network: the services are played by httpx's mock transport."""

from __future__ import annotations

import json
import re
import threading
from datetime import date
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from previewit.adapters.ai.catalog import (
    Catalogue,
    CatalogueError,
    LocalModels,
    load_catalogue,
)
from previewit.adapters.ai.jobs import ThreadedAiJobs
from previewit.adapters.ai.writers import HttpAiWriter
from previewit.application.ai_reviews import DEFAULT_PRICING, AiPrompt, AiServiceError
from previewit.domain.ai_models import MAX_LISTED, ModelCard, suggest
from previewit.domain.ai_reviews import AiReviewId

KEY = "sk-secret-0123456789abcdef"
PROMPT = AiPrompt("Be a reviewer.", "Title: X\n<<<WORK\nHello\nWORK>>>", 2_000)


# -- the catalogue -------------------------------------------------------------------------------


def test_the_catalogue_file_is_complete_and_recent() -> None:
    services, cards = load_catalogue()
    assert {"anthropic", "openai", "google", "mistral", "huggingface"} <= set(services)
    assert len(cards) <= MAX_LISTED  # "See more" shows them all
    assert len({c.maker for c in cards}) >= 6  # the famous ones
    for card in cards:
        assert card.service in services and card.key_label and card.key_url.startswith("https://")
        assert card.checked is not None and card.checked >= date(2026, 11, 1), card.key
        assert Decimal(0) < card.input_usd < Decimal(20) and card.output_usd < Decimal(100)
    assert all(services[c.service].url.startswith("https://") for c in cards)


def test_an_essay_gets_three_suggestions_from_three_makers() -> None:
    _, cards = load_catalogue()
    picks, more = suggest(cards, 30_000, DEFAULT_PRICING)
    assert len(picks) == 3 and len({p.card.maker for p in picks}) == 3
    assert picks[0].card.tier == 3
    assert len(picks) + len(more) == len(cards)


def test_a_broken_catalogue_says_where(tmp_path: Path) -> None:
    bad = tmp_path / "models.toml"
    bad.write_text('[services.x]\nname = "X"\napi = "carrier-pigeon"\nurl = "https://x"\n')
    with pytest.raises(CatalogueError, match=r"services\.x"):
        load_catalogue(bad)
    bad.write_text('[[models]]\nkey = "a/b"\nservice = "nobody"\n')
    with pytest.raises(CatalogueError, match="unknown service"):
        load_catalogue(bad)


def ollama(models: list[str], *, fail: bool = False) -> httpx.MockTransport:
    def handle(request: httpx.Request) -> httpx.Response:
        if fail:
            raise httpx.ConnectError("no route", request=request)
        assert request.url.path == "/api/tags"
        return httpx.Response(200, json={"models": [{"name": m} for m in models]})

    return httpx.MockTransport(handle)


def local(transport: httpx.BaseTransport, **kw: object) -> LocalModels:
    options: dict = {"place": "Finland", "country": "FI", "context": 8192, **kw}
    return LocalModels("http://bc250.lan:11434/", transport=transport, **options)


def test_the_models_on_previewits_server_are_free_and_come_first() -> None:
    found = local(ollama(["qwen3:8b", "nomic-embed-text:latest", "gemma3:12b"]))
    _, cards = load_catalogue()
    listed = Catalogue(cards, found).cards()
    assert [c.key for c in listed[:2]] == ["local/gemma3:12b", "local/qwen3:8b"]
    gemma = listed[0]
    assert gemma.free and gemma.maker == "Google" and gemma.flag == "\U0001f1eb\U0001f1ee"
    assert gemma.hosting == "Previewit's own server, Finland" and gemma.context_tokens == 8192
    assert listed[2:] == cards


def test_the_server_can_offer_only_some_models() -> None:
    found = local(ollama(["qwen3:8b", "gemma3:12b", "llama3.1:8b"]), only=("llama3.1:8b", "x:1"))
    assert [c.name for c in found.cards()] == ["llama3.1:8b"]


def test_an_unreachable_server_offers_nothing_and_is_asked_again_later() -> None:
    now = [0.0]
    found = LocalModels(
        "http://bc250.lan:11434", place="Finland", country="FI", context=8192,
        transport=ollama([], fail=True), clock=lambda: now[0],
    )  # fmt: skip
    assert found.cards() == []
    found._transport = ollama(["qwen3:8b"])
    assert found.cards() == []  # remembered for a few minutes
    now[0] += 301
    assert [c.name for c in found.cards()] == ["qwen3:8b"]


# -- asking the services -------------------------------------------------------------------------


class Service:
    """Plays a model service: records what it was sent and answers as told."""

    def __init__(self, status: int = 200, body: object | None = None) -> None:
        self.status = status
        self.body = body
        self.seen: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.seen.append(request)
        if isinstance(self.body, Exception):
            raise self.body
        return httpx.Response(self.status, json=self.body)

    @property
    def sent(self) -> dict:
        return json.loads(self.seen[-1].content)


def writer(service: Service) -> HttpAiWriter:
    services, _ = load_catalogue()
    return HttpAiWriter(
        services,
        ollama_url="http://bc250.lan:11434",
        user_agent="PreviewitTest/1",
        transport=httpx.MockTransport(service),
    )


def card(key: str) -> ModelCard:
    _, cards = load_catalogue()
    return next(c for c in cards if c.key == key)


def test_anthropic_gets_the_key_in_its_header_and_the_prompt_as_messages() -> None:
    service = Service(body={
        "content": [{"type": "text", "text": "Summary\nGood."}],
        "usage": {"input_tokens": 120, "output_tokens": 30},
    })  # fmt: skip
    answer = writer(service).write(card("anthropic/claude-sonnet-5-5"), KEY, PROMPT)
    assert (answer.text, answer.input_tokens, answer.output_tokens) == ("Summary\nGood.", 120, 30)
    request = service.seen[0]
    assert request.url == "https://api.anthropic.com/v1/messages"
    assert request.headers["x-api-key"] == KEY and "authorization" not in request.headers
    assert service.sent["model"] == "claude-sonnet-5-5" and service.sent["max_tokens"] == 2_000
    assert service.sent["system"] == PROMPT.system
    assert service.sent["messages"] == [{"role": "user", "content": PROMPT.user}]


def test_openai_style_services_get_a_bearer_key() -> None:
    service = Service(body={
        "choices": [{"message": {"content": "<think>hmm</think>\nSummary\nFine."}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 20},
    })  # fmt: skip
    answer = writer(service).write(card("openai/gpt-6.1-sol"), KEY, PROMPT)
    assert answer.text == "Summary\nFine."  # its thinking is left out
    request = service.seen[0]
    assert request.url == "https://api.openai.com/v1/chat/completions"
    assert request.headers["authorization"] == f"Bearer {KEY}"
    assert service.sent["max_completion_tokens"] == 2_000  # OpenAI's name for it
    writer(service).write(card("mistral/mistral-large-3"), KEY, PROMPT)
    assert service.seen[-1].url.host == "api.mistral.ai" and service.sent["max_tokens"] == 2_000
    writer(service).write(card("huggingface/gpt-oss-120b"), KEY, PROMPT)
    assert service.sent["model"] == "openai/gpt-oss-120b:cheapest"


def test_previewits_own_server_needs_no_key() -> None:
    service = Service(body={
        "message": {"role": "assistant", "content": "Summary\nNice."},
        "prompt_eval_count": 90, "eval_count": 12,
    })  # fmt: skip
    found = local(ollama(["qwen3:8b"])).cards()[0]
    answer = writer(service).write(found, "", PROMPT)
    assert (answer.text, answer.input_tokens, answer.output_tokens) == ("Summary\nNice.", 90, 12)
    assert service.seen[0].url == "http://bc250.lan:11434/api/chat"
    assert service.sent["options"] == {"num_ctx": 8192, "num_predict": 2_000}
    assert service.sent["stream"] is False and "authorization" not in service.seen[0].headers


@pytest.mark.parametrize(
    ("status", "body", "reason"),
    [
        (401, {"error": f"invalid key {KEY}"}, "refused the key"),
        (402, {}, "no credit"),
        (404, {}, "does not offer"),
        (429, {}, "busy"),
        (503, {}, "problem right now (answer 503)"),
        (400, {"error": f"bad {KEY}"}, "turned the request down (answer 400)"),
        (200, {"choices": []}, "could not read"),
        (200, ["not", "an", "object"], "could not read"),
    ],
)
def test_what_goes_wrong_is_said_in_words_and_never_repeats_the_key(
    status: int, body: object, reason: str
) -> None:
    with pytest.raises(AiServiceError, match=re.escape(reason)) as caught:
        writer(Service(status, body)).write(card("openai/gpt-6.1-terra"), KEY, PROMPT)
    assert KEY not in str(caught.value)


def test_a_service_that_cannot_be_reached_or_is_too_slow_is_said_so() -> None:
    gone = Service(body=httpx.ConnectError("refused"))
    with pytest.raises(AiServiceError, match="could not reach Google"):
        writer(gone).write(card("google/gemini-3-flash"), KEY, PROMPT)
    slow = Service(body=httpx.ReadTimeout("slow"))
    with pytest.raises(AiServiceError, match="took too long"):
        writer(slow).write(card("google/gemini-3-flash"), KEY, PROMPT)


# -- the queue -----------------------------------------------------------------------------------


def test_the_queue_runs_each_job_once_in_the_background() -> None:
    done: list[tuple[str, str, str]] = []
    jobs = ThreadedAiJobs(workers=2, local_workers=1)
    jobs.bind(lambda review_id, key: done.append((review_id, key, threading.current_thread().name)))
    jobs.start(AiReviewId("a"), KEY, free=False)
    jobs.start(AiReviewId("b"), "", free=True)
    jobs.wait()
    assert sorted((r, k) for r, k, _ in done) == [("a", KEY), ("b", "")]
    assert all(name.startswith("ai-review-") for _, _, name in done)
    assert next(name for r, _, name in done if r == "b").startswith("ai-review-local")


def test_a_job_that_breaks_does_not_stop_the_queue() -> None:
    done: list[str] = []

    def run(review_id: AiReviewId, key: str) -> None:
        if review_id == "bad":
            raise RuntimeError(key)
        done.append(review_id)

    jobs = ThreadedAiJobs(workers=1, local_workers=1)
    jobs.bind(run)
    jobs.start(AiReviewId("bad"), KEY, free=False)
    jobs.start(AiReviewId("good"), KEY, free=False)
    jobs.wait()
    assert done == ["good"]
