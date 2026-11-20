"""AI reviews on the web (ADR 0025): suggest models for a work, ask them, show their reviews.

Two places ask: the request form, before the work is sent (the quick review routes call the
helpers here), and the page of a Submission, for its author and the organizers. Keys arrive in
password fields, go to the service for one request and are never put back in a page.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import FormData, UploadFile
from starlette.responses import Response

from previewit.adapters.web.calls_routes import MAX_BODY_BYTES
from previewit.adapters.web.kit import WebKit
from previewit.adapters.web.limits import RateLimiter
from previewit.adapters.web.tenancy_routes import current_user
from previewit.application.ai_reviews import AiChoice, AiReviewsService, InvalidAiRequest
from previewit.application.artifacts import ArtifactError, Upload
from previewit.domain.ai_models import MAX_PER_REQUEST, ModelCard, Suggestion
from previewit.domain.ai_reviews import AiReviewStatus
from previewit.domain.calls import SubmissionId

READ_LIMIT = 10_000_001
CENT = Decimal("0.01")


def usd(value: Decimal | float | int) -> str:
    """Dollars for people: "$0.04", "less than $0.01", "free"."""
    amount = Decimal(str(value))
    if amount == 0:
        return "free"
    if amount < CENT:
        return "less than $0.01"
    return f"${amount.quantize(CENT, rounding=ROUND_HALF_UP)}"


def _keys(suggestions: Sequence[Suggestion]) -> list[dict[str, Any]]:
    """One key field per service the listed models need, in the order they appear."""
    found: dict[str, dict[str, Any]] = {}
    for s in suggestions:
        card = s.card
        if card.free:
            continue
        entry = found.setdefault(
            card.service,
            {"service": card.service, "label": card.key_label, "url": card.key_url, "for": []},
        )
        entry["for"].append(card.name)
    return list(found.values())


async def choices_context(
    ai: AiReviewsService,
    upload: Upload | None,
    *,
    read_pages: bool,
    chosen: Sequence[str] = (),
    error: str | None = None,
    chars: int | None = None,
) -> dict[str, Any]:
    """What `_ai_choices.html` needs: three suggestions, the others, and the key fields."""
    context: dict[str, Any] = {
        "picks": [], "more": [], "keys_shown": [], "keys_more": [], "chosen": list(chosen),
        "exact": True, "ai_error": error, "max_ai": MAX_PER_REQUEST, "chars": chars,
    }  # fmt: skip
    if chars is None:
        if upload is None:
            context["ai_error"] = error or (
                "Add your work above first (a file, a web page or pasted text), then ask again."
            )
            return context
        try:
            chars, exact = await run_in_threadpool(
                lambda: ai.measure(upload, read_pages=read_pages)
            )
        except ArtifactError as problem:
            context["ai_error"] = str(problem)
            return context
        context["exact"] = exact
        context["chars"] = chars
    picks, more = await run_in_threadpool(ai.suggestions, chars)
    shown = _keys(picks)
    context.update(
        picks=picks,
        more=more,
        keys_shown=shown,
        keys_more=[k for k in _keys(more) if k["service"] not in {s["service"] for s in shown}],
    )
    if not picks and not context["ai_error"]:
        context["ai_error"] = "No AI model on offer can read a work this long in one go."
    return context


def choices_from(form: FormData, cards: Sequence[ModelCard]) -> list[AiChoice]:
    """The models ticked, each with the key typed for its service."""
    by_key = {card.key: card for card in cards}
    choices: list[AiChoice] = []
    for model in WebKit.texts(form, "ai_model"):
        card = by_key.get(model)
        key = WebKit.text(form, f"ai_key_{card.service}") if card and not card.free else ""
        choices.append(AiChoice(model, key))
    return choices


async def upload_from(form: FormData) -> Upload | None:
    """The work as the request form has it so far: a file, a web page or pasted text."""
    value = form.get("file")
    if isinstance(value, UploadFile) and value.filename:
        content = await value.read(READ_LIMIT)
        await value.seek(0)  # the request form reads it again
        return Upload(content=content, filename=value.filename)
    address = WebKit.text(form, "web_address").strip()
    if address:
        return Upload(url=address)
    text = WebKit.text(form, "text")
    return Upload(text=text) if text.strip() else None


def build_ai_router(*, ai: AiReviewsService, kit: WebKit, visitors: RateLimiter) -> APIRouter:
    router = APIRouter()
    run = run_in_threadpool

    def too_big(request: Request) -> bool:
        try:
            return int(request.headers.get("content-length", "0")) > MAX_BODY_BYTES
        except ValueError:
            return True

    @router.post("/review/ai/suggest", response_class=HTMLResponse)
    async def suggest_for_the_form(request: Request) -> Response:
        """The person said yes: suggest models for the work in the form. No model is asked."""
        if too_big(request):
            return HTMLResponse("That upload is too large.", 413)
        form = await kit.checked_form(request)
        if form is None:
            return kit.forbidden()
        user = request.state.user
        if user is None and not visitors.allow(request.client.host if request.client else "?"):
            context = await choices_context(
                ai, None, read_pages=False, error="Too many tries. Wait a few minutes."
            )
            return kit.render(request, "_ai_choices.html", context, 429)
        upload = await upload_from(form)
        context = await choices_context(
            ai, upload, read_pages=user is not None, chosen=kit.texts(form, "ai_model")
        )
        return kit.render(request, "_ai_choices.html", context)

    # -- on a Submission's page ----------------------------------------------------------------

    async def section(
        request: Request, submission_id: str, *, ask: dict[str, Any] | None = None
    ) -> Response:
        user = current_user(request)
        sid = SubmissionId(submission_id)
        reviews = await run(ai.reviews_for, user.id, sid)
        return kit.render(
            request,
            "_ai_section.html",
            {"sid": submission_id, **_listing(reviews), "ask": ask, **(ask or {})},
        )

    @router.get("/submissions/{submission_id}/ai", response_class=HTMLResponse)
    async def ai_section(request: Request, submission_id: str) -> Response:
        return await section(request, submission_id)

    @router.get("/submissions/{submission_id}/ai/list", response_class=HTMLResponse)
    async def ai_list(request: Request, submission_id: str) -> Response:
        user = current_user(request)
        reviews = await run(ai.reviews_for, user.id, SubmissionId(submission_id))
        return kit.render(request, "_ai_list.html", {"sid": submission_id, **_listing(reviews)})

    async def ask_context(
        request: Request,
        submission_id: str,
        *,
        chosen: Sequence[str] = (),
        error: str | None = None,
    ) -> dict[str, Any]:
        user = current_user(request)
        try:
            chars = await run(ai.measure_submission, user.id, SubmissionId(submission_id))
        except InvalidAiRequest as problem:
            return await choices_context(ai, None, read_pages=True, error=str(problem))
        return await choices_context(
            ai, None, read_pages=True, chosen=chosen, error=error, chars=chars
        )

    @router.get("/submissions/{submission_id}/ai/ask", response_class=HTMLResponse)
    async def ai_ask(request: Request, submission_id: str) -> Response:
        context = await ask_context(request, submission_id)
        return kit.render(request, "_ai_ask.html", {"sid": submission_id, **context})

    @router.post("/submissions/{submission_id}/ai", response_class=HTMLResponse)
    async def ask_ai(request: Request, submission_id: str) -> Response:
        form = await kit.checked_form(request)
        if form is None:
            return kit.forbidden()
        user = current_user(request)
        choices = choices_from(form, await run(ai.cards))
        note = kit.text(form, "ai_note")
        try:
            await run(lambda: ai.request(user.id, SubmissionId(submission_id), choices, note=note))
        except InvalidAiRequest as problem:
            ask = await ask_context(
                request, submission_id, chosen=[c.model_key for c in choices], error=str(problem)
            )
            return await section(request, submission_id, ask=ask)
        return await section(request, submission_id)

    return router


def _listing(reviews: Sequence[Any]) -> dict[str, Any]:
    waiting = any(r.status in (AiReviewStatus.WAITING, AiReviewStatus.WRITING) for r in reviews)
    return {"ai_reviews": list(reviews), "waiting": waiting}
