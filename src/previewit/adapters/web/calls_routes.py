"""Calls, submissions, revisions and review by link."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import FormData, UploadFile
from starlette.responses import Response

from previewit.adapters.web.kit import WebKit
from previewit.adapters.web.tenancy_routes import current_user
from previewit.application.artifacts import ArtifactError, ArtifactType, UnknownArtifactType, Upload
from previewit.application.calls import (
    AlreadySubmitted,
    CallClosed,
    CallHasSubmissions,
    CallsService,
    InvalidShare,
    ShareLimitReached,
)
from previewit.domain.calls import CallId, InvalidCall, ShareTarget, SubmissionId
from previewit.domain.identity import User
from previewit.domain.tenancy import GroupId, SpaceId

# Larger bodies are refused before they are read. A reverse proxy should enforce the same
# limit for requests that do not announce their size.
MAX_BODY_BYTES = 12_000_000


def parse_deadline(value: str) -> datetime | None:
    """`datetime-local` input, read as UTC."""
    value = value.strip()
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M").replace(tzinfo=UTC)
    except ValueError:
        raise InvalidCall("Use a date and time like 2026-12-31 23:59.") from None


def _safe_filename(name: str | None) -> str:
    return re.sub(r"[^\w.\- ]", "_", name or "file")[:120] or "file"


async def read_upload(form: FormData, artifact_type: ArtifactType) -> Upload:
    """Turn the submitted form into an Upload for the plugin, whatever the plugin's input kind."""
    if artifact_type.input_kind == "text":
        value = form.get("text")
        return Upload(text=value if isinstance(value, str) else "")
    value = form.get("file")
    if isinstance(value, UploadFile) and value.filename:
        content = await value.read(artifact_type.max_bytes + 1)
        return Upload(content=content, filename=value.filename)
    return Upload()


def build_calls_router(*, calls: CallsService, kit: WebKit) -> APIRouter:
    router = APIRouter()
    run = run_in_threadpool

    def words(view: Any) -> Any:
        preset = view.preset
        return preset.word if preset else (lambda concept: concept)

    def call_page(
        request: Request,
        user: User,
        call_id: str,
        *,
        error: str | None = None,
        new_link: str | None = None,
        status: int = 200,
    ) -> Response:
        view = calls.call_view(user.id, CallId(call_id))
        manage = "calls.manage" in {p.value for p in view.permissions}
        shares = calls.shares(user.id, ShareTarget.CALL, call_id) if manage else []
        return kit.render(
            request,
            "call.html",
            {
                "page_title": view.call.title,
                "view": view,
                "word": words(view),
                "manage": manage,
                "shares": shares,
                "types": calls.artifact_types(),
                "error": error,
                "new_link": new_link,
                "closes_value": view.call.closes_at.strftime("%Y-%m-%dT%H:%M")
                if view.call.closes_at
                else "",
            },
            status,
        )

    def submission_page(
        request: Request,
        user: User,
        submission_id: str,
        *,
        rev: int | None = None,
        error: str | None = None,
        new_link: str | None = None,
        status: int = 200,
    ) -> Response:
        sid = SubmissionId(submission_id)
        view = calls.submission_view(user.id, sid)
        shown = view.latest if rev is None else calls.revision(user.id, sid, rev)
        shares = (
            calls.shares(user.id, ShareTarget.SUBMISSION, submission_id) if view.can_share else []
        )
        raw = f"/submissions/{submission_id}/revisions/{shown.number}/raw"
        return kit.render(
            request,
            "submission.html",
            {
                "page_title": view.submission.title,
                "view": view,
                "shown": shown,
                "body": view.artifact_type.render_html(shown.artifact, raw),
                "raw_url": raw,
                "shares": shares,
                "error": error,
                "new_link": new_link,
            },
            status,
        )

    def too_big(request: Request) -> bool:
        try:
            return int(request.headers.get("content-length", "0")) > MAX_BODY_BYTES
        except ValueError:
            return True

    def too_big_response() -> Response:
        return HTMLResponse("That upload is too large.", 413)

    # -- calls ---------------------------------------------------------------------------------

    def calls_page(
        request: Request, user: User, space_id: str, error: str | None = None, status: int = 200
    ) -> Response:
        info = calls.space_calls(user.id, SpaceId(space_id))
        return kit.render(
            request,
            "calls.html",
            {
                "page_title": info.preset.word("calls").capitalize(),
                "space": info.space,
                "calls": info.calls,
                "manage": info.can_manage,
                "word": info.preset.word,
                "types": calls.artifact_types(),
                "error": error,
            },
            status,
        )

    @router.get("/spaces/{space_id}/calls", response_class=HTMLResponse)
    async def call_list(request: Request, space_id: str) -> Response:
        return await run(calls_page, request, current_user(request), space_id)

    @router.post("/spaces/{space_id}/calls")
    async def create_call(request: Request, space_id: str) -> Response:
        form = await kit.checked_form(request)
        if form is None:
            return kit.forbidden()
        user = current_user(request)
        try:
            call = await run(
                lambda: calls.create_call(
                    user.id,
                    SpaceId(space_id),
                    title=kit.text(form, "title"),
                    description=kit.text(form, "description"),
                    artifact_type=kit.text(form, "artifact_type"),
                    group_work=kit.text(form, "group_work") == "on",
                    closes_at=parse_deadline(kit.text(form, "closes_at")),
                    published=kit.text(form, "published") == "on",
                )
            )
        except (InvalidCall, UnknownArtifactType) as e:
            message = str(e) if isinstance(e, InvalidCall) else "Choose a kind of work."
            return await run(calls_page, request, user, space_id, message, 400)
        return RedirectResponse(f"/calls/{call.id}", status_code=303)

    @router.get("/calls/{call_id}", response_class=HTMLResponse)
    async def call_detail(request: Request, call_id: str) -> Response:
        return await run(call_page, request, current_user(request), call_id)

    @router.post("/calls/{call_id}/edit")
    async def edit_call(request: Request, call_id: str) -> Response:
        form = await kit.checked_form(request)
        if form is None:
            return kit.forbidden()
        user = current_user(request)
        try:
            await run(
                lambda: calls.update_call(
                    user.id,
                    CallId(call_id),
                    title=kit.text(form, "title"),
                    description=kit.text(form, "description"),
                    closes_at=parse_deadline(kit.text(form, "closes_at")),
                    published=kit.text(form, "published") == "on",
                )
            )
        except InvalidCall as e:
            message = str(e)
            return await run(lambda: call_page(request, user, call_id, error=message, status=400))
        return RedirectResponse(f"/calls/{call_id}", status_code=303)

    @router.post("/calls/{call_id}/delete")
    async def delete_call(request: Request, call_id: str) -> Response:
        form = await kit.checked_form(request)
        if form is None:
            return kit.forbidden()
        user = current_user(request)
        space_id = (await run(calls.call_view, user.id, CallId(call_id))).call.space_id
        try:
            await run(calls.delete_call, user.id, CallId(call_id))
        except CallHasSubmissions:
            message = "This call has submissions, so it cannot be deleted. Unpublish it instead."
            return await run(lambda: call_page(request, user, call_id, error=message, status=400))
        return RedirectResponse(f"/spaces/{space_id}/calls", status_code=303)

    # -- submissions ---------------------------------------------------------------------------

    @router.post("/calls/{call_id}/submissions")
    async def submit(request: Request, call_id: str) -> Response:
        if too_big(request):
            return too_big_response()
        form = await kit.checked_form(request)
        if form is None:
            return kit.forbidden()
        user = current_user(request)
        view = await run(calls.call_view, user.id, CallId(call_id))
        try:
            upload = await read_upload(form, view.artifact_type)
            group = kit.text(form, "group_id")
            submission = await run(
                lambda: calls.submit(
                    user.id,
                    CallId(call_id),
                    title=kit.text(form, "title"),
                    upload=upload,
                    group_id=GroupId(group) if group else None,
                )
            )
        except (InvalidCall, ArtifactError) as e:
            message = str(e)
            return await run(lambda: call_page(request, user, call_id, error=message, status=400))
        except AlreadySubmitted:
            message = "That has already been submitted. Open it and add a new revision."
            return await run(lambda: call_page(request, user, call_id, error=message, status=400))
        except CallClosed:
            message = "This call is not accepting work."
            return await run(lambda: call_page(request, user, call_id, error=message, status=403))
        return RedirectResponse(f"/submissions/{submission.id}", status_code=303)

    @router.get("/submissions/{submission_id}", response_class=HTMLResponse)
    async def submission_detail(request: Request, submission_id: str, rev: int | None = None):
        user = current_user(request)
        return await run(lambda: submission_page(request, user, submission_id, rev=rev))

    @router.post("/submissions/{submission_id}/revisions")
    async def add_revision(request: Request, submission_id: str) -> Response:
        if too_big(request):
            return too_big_response()
        form = await kit.checked_form(request)
        if form is None:
            return kit.forbidden()
        user = current_user(request)
        sid = SubmissionId(submission_id)
        view = await run(calls.submission_view, user.id, sid)
        try:
            upload = await read_upload(form, view.artifact_type)
            await run(calls.revise, user.id, sid, upload)
        except ArtifactError as e:
            message = str(e)
            return await run(
                lambda: submission_page(request, user, submission_id, error=message, status=400)
            )
        except CallClosed:
            message = "This call is not accepting work any more."
            return await run(
                lambda: submission_page(request, user, submission_id, error=message, status=403)
            )
        return RedirectResponse(f"/submissions/{submission_id}", status_code=303)

    @router.get("/submissions/{submission_id}/revisions/{number}/raw")
    async def raw_revision(request: Request, submission_id: str, number: int) -> Response:
        user = current_user(request)
        revision = await run(calls.revision, user.id, SubmissionId(submission_id), number)
        artifact = revision.artifact
        name = _safe_filename(artifact.filename or f"{artifact.type_key}-{number}")
        return Response(
            artifact.content,
            media_type=artifact.media_type,
            headers={
                "X-Content-Type-Options": "nosniff",
                "Content-Disposition": f'inline; filename="{name}"',
                "Cache-Control": "private, no-store",
            },
        )

    # -- review by link ----------------------------------------------------------------------

    async def create_share(request: Request, target: ShareTarget, target_id: str, page) -> Response:
        form = await kit.checked_form(request)
        if form is None:
            return kit.forbidden()
        user = current_user(request)
        try:
            _, token = await run(calls.create_share, user.id, target, target_id)
        except ShareLimitReached:
            message = "You have reached the sharing limit of your plan."
            return await run(lambda: page(request, user, target_id, error=message, status=403))
        link = f"{kit.settings.origin}/s/{token}"
        return await run(lambda: page(request, user, target_id, new_link=link))

    @router.post("/calls/{call_id}/shares")
    async def share_call(request: Request, call_id: str) -> Response:
        return await create_share(request, ShareTarget.CALL, call_id, call_page)

    @router.post("/submissions/{submission_id}/shares")
    async def share_submission(request: Request, submission_id: str) -> Response:
        return await create_share(request, ShareTarget.SUBMISSION, submission_id, submission_page)

    async def revoke(request: Request, target: ShareTarget, target_id: str, link_id: str, back):
        form = await kit.checked_form(request)
        if form is None:
            return kit.forbidden()
        user = current_user(request)
        await run(calls.revoke_share, user.id, target, target_id, link_id)
        return RedirectResponse(back, status_code=303)

    @router.post("/calls/{call_id}/shares/{link_id}/revoke")
    async def revoke_call_share(request: Request, call_id: str, link_id: str) -> Response:
        return await revoke(request, ShareTarget.CALL, call_id, link_id, f"/calls/{call_id}")

    @router.post("/submissions/{submission_id}/shares/{link_id}/revoke")
    async def revoke_submission_share(
        request: Request, submission_id: str, link_id: str
    ) -> Response:
        return await revoke(
            request, ShareTarget.SUBMISSION, submission_id, link_id, f"/submissions/{submission_id}"
        )

    @router.get("/s/{token}", response_class=HTMLResponse)
    async def share_page(request: Request, token: str) -> Response:
        preview = await run(calls.preview_share, token)
        if preview is None:
            raise InvalidShare
        return kit.render(
            request,
            "share.html",
            {"page_title": preview.title, "preview": preview, "token": token},
        )

    @router.post("/s/{token}")
    async def open_share(request: Request, token: str) -> Response:
        form = await kit.checked_form(request)
        if form is None:
            return kit.forbidden()
        user = current_user(request)
        item = await run(calls.accept_share, user.id, token)
        prefix = "calls" if item.target is ShareTarget.CALL else "submissions"
        return RedirectResponse(f"/{prefix}/{item.target_id}", status_code=303)

    @router.get("/shared", response_class=HTMLResponse)
    async def shared_with_me(request: Request) -> Response:
        user = current_user(request)
        items = await run(calls.shared_with_me, user.id)
        return kit.render(request, "shared.html", {"page_title": "Shared with you", "items": items})

    return router
