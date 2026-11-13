"""The reviewer's side of the call for reviewers: open a personal invitation link."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool
from starlette.responses import Response

from previewit.adapters.web.kit import WebKit
from previewit.adapters.web.tenancy_routes import current_user
from previewit.application.invitations import InvalidInvitationLink, InvitationsService


def build_invitations_router(*, invitations: InvitationsService, kit: WebKit) -> APIRouter:
    router = APIRouter()
    run = run_in_threadpool

    @router.get("/i/{token}", response_class=HTMLResponse)
    async def invitation_page(request: Request, token: str) -> Response:
        preview = await run(invitations.preview, token)
        if preview is None:
            raise InvalidInvitationLink
        user = getattr(request.state, "user", None)
        state = await run(invitations.readiness, user.id, token) if user else None
        return kit.render(
            request,
            "invitation.html",
            {
                "page_title": f"Review: {preview.call_title}",
                "preview": preview,
                "token": token,
                "state": state,
            },
        )

    @router.post("/i/{token}")
    async def open_invitation(request: Request, token: str) -> Response:
        form = await kit.checked_form(request)
        if form is None:
            return kit.forbidden()
        user = current_user(request)
        accepted = await run(invitations.accept, user.id, token)
        return RedirectResponse(f"/spaces/{accepted.space_id}/reviews", status_code=303)

    return router
