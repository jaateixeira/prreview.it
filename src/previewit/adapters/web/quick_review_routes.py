"""Request a review: one page from a file and some people to invitations sent (ADR 0018)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, time, tzinfo
from pathlib import PurePath
from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import FormData, UploadFile
from starlette.responses import Response

from previewit.adapters.web.ai_routes import choices_context, choices_from, upload_from
from previewit.adapters.web.calls_routes import MAX_BODY_BYTES
from previewit.adapters.web.kit import WebKit
from previewit.adapters.web.limits import RateLimiter
from previewit.adapters.web.local_time import BadTime, parse_day_time, viewer_zone
from previewit.adapters.web.pages_routes import check_page
from previewit.adapters.web.tenancy_routes import current_user
from previewit.application.ai_reviews import AiReviewsService, InvalidAiRequest
from previewit.application.artifacts import ArtifactError, Upload
from previewit.application.prepared_requests import (
    VISITOR,
    InvalidPreparedRequest,
    PreparedRequestsService,
)
from previewit.application.quick_review import (
    DUE_TIME,
    InvalidReviewRequest,
    QuickReviewService,
    ReviewRequest,
)
from previewit.application.tenancy import NotFound, VerificationRequired
from previewit.application.web_pages import PageChecker
from previewit.domain.email_list import (
    MAX_EMAILS,
    MAX_FILE_BYTES,
    SAMPLES,
    EmailList,
    EmailListError,
    merge,
    parse_file,
    parse_typed,
)
from previewit.domain.identity import User

# One byte more than the largest file Previewit reviews, so the plugin can say "too large".
READ_LIMIT = 10_000_001


@dataclass
class Draft:
    """What the person has typed so far; shown again when something needs fixing."""

    title: str = ""
    text: str = ""
    web_address: str = ""
    kept_file: str = ""  # the name of a file kept while its owner signed in (ADR 0024)
    emails: str = ""
    cover_letter: str = ""
    due: str = ""
    due_time: str = "16:00"
    send_emails: bool = True


def emails_text(found: EmailList) -> str:
    """The box content after a merge: the good addresses, then what still needs fixing."""
    return "\n".join([email.value for email in found.emails] + list(found.invalid))


def title_from(filename: str) -> str:
    return PurePath(filename.replace("\\", "/")).stem.replace("_", " ").replace("-", " ").strip()


def parse_due(day: str, at: str = "", zone: tzinfo = UTC) -> tuple[datetime | None, time]:
    """The due day and time in the viewer's zone, as UTC (None: the service picks two weeks
    from today), and the time of day (16:00 unless another was typed)."""
    try:
        at_time = datetime.strptime(at.strip(), "%H:%M").time() if at.strip() else DUE_TIME
        return parse_day_time(day, at, zone), at_time
    except (BadTime, ValueError) as problem:
        message = str(problem) if isinstance(problem, BadTime) else "Write the time like 16:00."
        raise InvalidReviewRequest(message) from None


async def uploaded(form: FormData, key: str) -> tuple[str, bytes] | None:
    value = form.get(key)
    if isinstance(value, UploadFile) and value.filename:
        return value.filename, await value.read(READ_LIMIT)
    return None


def too_big(request: Request) -> bool:
    try:
        return int(request.headers.get("content-length", "0")) > MAX_BODY_BYTES
    except ValueError:
        return True


def build_quick_review_router(
    *,
    quick: QuickReviewService,
    kit: WebKit,
    pages: PageChecker,
    prepared: PreparedRequestsService,
    visitors: RateLimiter,
    ai: AiReviewsService | None = None,
) -> APIRouter:
    """Request a review. Visitors may fill it in too (ADR 0024): Send it out keeps their form,
    file included, and sends them to sign in; they come back to it filled in. AI models may
    review it too (ADR 0025)."""
    router = APIRouter()
    run = run_in_threadpool

    def form_page(
        request: Request,
        draft: Draft,
        *,
        error: str | None = None,
        found: EmailList | None = None,
        status: int = 200,
        extra: dict[str, object] | None = None,
    ) -> Response:
        user: User | None = request.state.user
        return kit.render(
            request,
            "review_new.html",
            {
                "page_title": "Request a review",
                "draft": draft,
                "error": error,
                "found": found if found is not None else parse_typed(draft.emails),
                "emails": draft.emails,
                "can_send": user.email_verified if user else True,
                "visitor": user is None,
                "live_check": user is not None,  # only accounts make Previewit fetch pages
                "samples": SAMPLES,
                "max_emails": MAX_EMAILS,
                **(extra or {}),
            },
            status,
        )

    @router.get("/review/new", response_class=HTMLResponse)
    async def new_review(request: Request) -> Response:
        user: User | None = request.state.user
        if user is not None and user.is_guest:  # a guest joins first (ADR 0020)
            return RedirectResponse("/account/new", status_code=303)
        return form_page(request, Draft())

    @router.get("/prepared/{token}", response_class=HTMLResponse)
    async def open_prepared(request: Request, token: str) -> Response:
        """A request an AI assistant prepared (ADR 0023), or the form a visitor filled in before
        signing in (ADR 0024): filled in again, to check and send."""
        if current_user(request).is_guest:
            return RedirectResponse("/account/new", status_code=303)
        found = await run(prepared.open, token)
        if found is None:
            return kit.render(request, "prepared_gone.html", {"page_title": "Request gone"}, 404)
        draft = Draft(
            title=found.title,
            text=found.text,
            web_address=found.web_address,
            emails="\n".join(found.reviewers),
            cover_letter=found.message,
            due=found.due,
            due_time=found.due_time or "16:00",
            kept_file=found.file_name if found.file_content is not None else "",
        )
        page, problem = (None, None)
        if found.web_address:
            page, problem = await check_page(pages, found.web_address)
        extra: dict[str, object] = {
            "prepared": token,
            "kept_for_visitor": found.source == VISITOR,
            "page": page,
            "problem": problem,
        }
        if ai is not None and found.ai_models:  # chosen before signing in; keys never kept
            if found.file_content is not None:
                work = Upload(content=found.file_content, filename=found.file_name)
            elif found.web_address:
                work = Upload(url=found.web_address)
            else:
                work = Upload(text=found.text) if found.text.strip() else None
            context = await choices_context(
                ai, work, read_pages=True, chosen=found.ai_models, user_id=current_user(request).id
            )
            extra.update(context, kept_ai_models=True)
        return form_page(request, draft, extra=extra)

    @router.get("/review/samples/{name}")
    async def sample(name: str) -> Response:
        found = SAMPLES.get(name)
        if found is None:
            raise NotFound
        return Response(
            found.content,
            media_type=found.content_type,
            headers={"Content-Disposition": f'attachment; filename="{name}"'},
        )

    @router.post("/review/emails/check", response_class=HTMLResponse)
    async def check_emails(request: Request) -> Response:
        form = await kit.checked_form(request)
        if form is None:
            return kit.forbidden()
        found = parse_typed(kit.text(form, "emails"))
        return kit.render(
            request,
            "_email_check.html",
            {"found": found, "max_emails": MAX_EMAILS},
        )

    @router.post("/review/emails/import", response_class=HTMLResponse)
    async def import_emails(request: Request) -> Response:
        if too_big(request):
            return HTMLResponse("That upload is too large.", 413)
        form = await kit.checked_form(request)
        if form is None:
            return kit.forbidden()
        typed = parse_typed(kit.text(form, "emails"))
        picked = await uploaded(form, "emails_file")
        error: str | None = None
        found = typed
        if picked is None:
            error = "Choose a file with the email addresses."
        else:
            try:
                found = merge(typed, parse_file(picked[0], picked[1][: MAX_FILE_BYTES + 1]))
            except EmailListError as problem:
                error = str(problem)
        shown = emails_text(found) if error is None else kit.text(form, "emails")
        return kit.render(
            request,
            "_reviewers_box.html",
            {"emails": shown, "found": found, "check_error": error, "max_emails": MAX_EMAILS},
        )

    async def keep_for_visitor(
        request: Request,
        draft: Draft,
        found: EmailList,
        picked: tuple[str, bytes] | None,
        again: Callable[[str, EmailList | None], Response],
        ai_models: list[str],
    ) -> Response:
        if picked is not None:
            try:  # the kind and size of a file can be checked now; a web page waits
                await run(quick.check_upload, Upload(content=picked[1], filename=picked[0]))
            except ArtifactError as problem:
                return again(str(problem), found)
        client = request.client.host if request.client else "unknown"
        if not visitors.allow(client):
            message = (
                "You saved several requests in a short time. Wait a few minutes and try again."
            )
            return form_page(request, draft, error=message, found=found, status=429)
        try:
            token = await run(
                lambda: prepared.keep_for_visitor(
                    title=draft.title, web_address=draft.web_address, text=draft.text,
                    reviewers=[email.value for email in found.emails],
                    message=draft.cover_letter, due=draft.due, due_time=draft.due_time,
                    file_name=picked[0] if picked else "",
                    file_content=picked[1] if picked else None,
                    ai_models=ai_models,  # the models only: keys are never kept
                )
            )  # fmt: skip
        except InvalidPreparedRequest as problem:
            return again(str(problem), found)
        next_url = quote(f"/prepared/{token}", safe="")
        return RedirectResponse(f"/login?next={next_url}", status_code=303)

    @router.post("/review")
    async def request_review(request: Request) -> Response:
        user: User | None = request.state.user
        if user is not None and user.is_guest:
            return RedirectResponse("/account/new", status_code=303)
        if too_big(request):
            return HTMLResponse("That upload is too large.", 413)
        form = await kit.checked_form(request)
        if form is None:
            return kit.forbidden()
        draft = Draft(
            title=kit.text(form, "title").strip(),
            text=kit.text(form, "text"),
            web_address=kit.text(form, "web_address").strip(),
            emails=kit.text(form, "emails"),
            cover_letter=kit.text(form, "cover_letter"),
            due=kit.text(form, "due").strip(),
            due_time=kit.text(form, "due_time").strip() or "16:00",
            send_emails=kit.text(form, "send_emails") == "on",
        )

        token = kit.text(form, "prepared")  # prepared by an assistant or kept for a visitor
        kept = await run(prepared.open, token) if token else None
        if kept is not None and kept.file_content is not None:
            draft.kept_file = kept.file_name
        keep: dict[str, object] = {"prepared": token} if token else {}

        # AI models chosen too (ADR 0025): shown again, keys left out, if anything needs fixing.
        ai_models = kit.texts(form, "ai_model") if ai is not None else []
        ai_context: dict[str, object] = {}
        if ai is not None and ai_models:
            work = await upload_from(form)
            if work is None and kept is not None and kept.file_content is not None:
                work = Upload(content=kept.file_content, filename=kept.file_name)
            ai_context = await choices_context(
                ai, work, read_pages=user is not None, chosen=ai_models,
                user_id=user.id if user is not None else None,
            )  # fmt: skip

        def again(message: str, found: EmailList | None = None) -> Response:
            extra = {**keep, **ai_context}
            return form_page(request, draft, error=message, found=found, status=400, extra=extra)

        # The people: typed, plus a file of addresses if one came along.
        found = parse_typed(draft.emails)
        listing = await uploaded(form, "emails_file")
        if listing is not None:
            try:
                found = merge(found, parse_file(listing[0], listing[1][: MAX_FILE_BYTES + 1]))
            except EmailListError as problem:
                return again(str(problem))
            draft.emails = emails_text(found)
        if found.invalid:
            return again("Fix or remove the addresses marked below.", found)
        if found.over_limit:
            return again(f"Ask up to {MAX_EMAILS} reviewers at a time.", found)

        # The work: a file, a web page's address, or pasted text.
        picked = await uploaded(form, "file")
        keeps_file = kept is not None and kept.file_content is not None
        if picked is None and keeps_file and not draft.web_address:
            assert kept is not None and kept.file_content is not None
            picked = (kept.file_name, kept.file_content)  # kept while they signed in
        if draft.web_address and (picked is not None or draft.text.strip()):
            return again("Give one thing to review: a file, a web page or pasted text.", found)
        if picked is not None:
            upload = Upload(content=picked[1], filename=picked[0])
            title = draft.title or title_from(picked[0])
        elif draft.web_address:
            upload, title = Upload(url=draft.web_address), draft.title  # the page names itself
        elif draft.text.strip():
            upload, title = Upload(text=draft.text), draft.title
        else:
            return again("Choose a file, give the address of a web page or paste your text.", found)

        if user is None:  # a visitor: keep the form, file included, while they sign in
            return await keep_for_visitor(request, draft, found, picked, again, ai_models)

        choices = choices_from(form, await run(ai.cards)) if ai is not None and ai_models else []
        if ai is not None and choices:  # checked before anything is made
            chars = ai_context.get("chars")
            if not isinstance(chars, int):
                return again(str(ai_context.get("ai_error") or "Check the work first."), found)
            try:
                await run(ai.check, user.id, choices, chars)
            except InvalidAiRequest as problem:
                return again(str(problem), found)

        zone = viewer_zone(request)
        try:
            due, due_time = parse_due(draft.due, draft.due_time, zone)
            result = await run(
                lambda: quick.request_review(
                    user.id,
                    ReviewRequest(
                        title=title,
                        upload=upload,
                        reviewers=found.emails,
                        cover_letter=draft.cover_letter,
                        send_emails=draft.send_emails,
                        due=due,
                        due_time=due_time,
                        zone=zone,
                    ),
                )
            )
        except (InvalidReviewRequest, ArtifactError) as problem:
            return again(str(problem), found)
        except VerificationRequired:
            return again(
                "Confirm your email address first (open your Account page): Previewit sends "
                "the invitations in your name.",
                found,
            )

        if token:
            await run(prepared.used, token)  # sent: the kept copy and its file go
        ai_started: list[object] = []
        ai_error: str | None = None
        if ai is not None and choices:
            asking, note = ai, draft.cover_letter
            try:
                ai_started = list(
                    await run(
                        lambda: asking.request(user.id, result.submission_id, choices, note=note)
                    )
                )
            except InvalidAiRequest as problem:
                ai_error = str(problem)
        base = kit.settings.base_url.rstrip("/")
        return kit.render(
            request,
            "review_done.html",
            {
                "page_title": "Review requested",
                "title": result.title or title,
                "result": result,
                "rows": [(invite, f"{base}/i/{invite.token}") for invite in result.invites],
                "ai_started": ai_started,
                "ai_error": ai_error,
            },
        )

    return router
