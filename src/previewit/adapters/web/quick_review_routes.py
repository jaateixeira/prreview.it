"""Request a review: one page from a file and some people to invitations sent (ADR 0018)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, time
from pathlib import PurePath

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import FormData, UploadFile
from starlette.responses import Response

from previewit.adapters.web.calls_routes import MAX_BODY_BYTES
from previewit.adapters.web.kit import WebKit
from previewit.adapters.web.tenancy_routes import current_user
from previewit.application.artifacts import ArtifactError, Upload
from previewit.application.quick_review import (
    InvalidReviewRequest,
    QuickReviewService,
    ReviewRequest,
)
from previewit.application.tenancy import NotFound, VerificationRequired
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

# One byte more than the largest file Previewit reviews, so the plugin can say "too large".
READ_LIMIT = 10_000_001


@dataclass
class Draft:
    """What the person has typed so far; shown again when something needs fixing."""

    title: str = ""
    text: str = ""
    emails: str = ""
    cover_letter: str = ""
    due: str = ""
    send_emails: bool = True


def emails_text(found: EmailList) -> str:
    """The box content after a merge: the good addresses, then what still needs fixing."""
    return "\n".join([email.value for email in found.emails] + list(found.invalid))


def title_from(filename: str) -> str:
    return PurePath(filename.replace("\\", "/")).stem.replace("_", " ").replace("-", " ").strip()


def parse_due(value: str) -> datetime | None:
    value = value.strip()
    if not value:
        return None
    try:
        day = datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise InvalidReviewRequest("Write the due date like 2026-12-31.") from None
    return datetime.combine(day, time(23, 59), UTC)


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


def build_quick_review_router(*, quick: QuickReviewService, kit: WebKit) -> APIRouter:
    router = APIRouter()
    run = run_in_threadpool

    def form_page(
        request: Request,
        draft: Draft,
        *,
        error: str | None = None,
        found: EmailList | None = None,
        status: int = 200,
    ) -> Response:
        user = current_user(request)
        return kit.render(
            request,
            "review_new.html",
            {
                "page_title": "Request a review",
                "draft": draft,
                "error": error,
                "found": found if found is not None else parse_typed(draft.emails),
                "emails": draft.emails,
                "can_send": user.email_verified,
                "samples": SAMPLES,
                "max_emails": MAX_EMAILS,
            },
            status,
        )

    @router.get("/review/new", response_class=HTMLResponse)
    async def new_review(request: Request) -> Response:
        return form_page(request, Draft())

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
        current_user(request)
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
        current_user(request)
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

    @router.post("/review")
    async def request_review(request: Request) -> Response:
        user = current_user(request)
        if too_big(request):
            return HTMLResponse("That upload is too large.", 413)
        form = await kit.checked_form(request)
        if form is None:
            return kit.forbidden()
        draft = Draft(
            title=kit.text(form, "title").strip(),
            text=kit.text(form, "text"),
            emails=kit.text(form, "emails"),
            cover_letter=kit.text(form, "cover_letter"),
            due=kit.text(form, "due").strip(),
            send_emails=kit.text(form, "send_emails") == "on",
        )

        def again(message: str, found: EmailList | None = None) -> Response:
            return form_page(request, draft, error=message, found=found, status=400)

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

        # The work: a file, or pasted text.
        picked = await uploaded(form, "file")
        if picked is not None:
            upload = Upload(content=picked[1], filename=picked[0])
            title = draft.title or title_from(picked[0])
        elif draft.text.strip():
            upload, title = Upload(text=draft.text), draft.title
        else:
            return again("Choose a file or paste your text.", found)

        try:
            result = await run(
                lambda: quick.request_review(
                    user.id,
                    ReviewRequest(
                        title=title,
                        upload=upload,
                        reviewers=found.emails,
                        cover_letter=draft.cover_letter,
                        send_emails=draft.send_emails,
                        due=parse_due(draft.due),
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

        base = kit.settings.base_url.rstrip("/")
        return kit.render(
            request,
            "review_done.html",
            {
                "page_title": "Review requested",
                "title": title,
                "result": result,
                "rows": [(invite, f"{base}/i/{invite.token}") for invite in result.invites],
            },
        )

    return router
