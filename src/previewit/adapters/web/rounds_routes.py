"""Review rounds for a call, allocation, manual pairing and "my reviews to do"."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import FormData
from starlette.responses import Response

from previewit.adapters.web.kit import WebKit
from previewit.adapters.web.tenancy_routes import current_user
from previewit.application.allocation import UnknownStrategy
from previewit.application.calls import CallsService
from previewit.application.rounds import RoundsService
from previewit.domain.calls import CallId, SubmissionId
from previewit.domain.identity import User
from previewit.domain.party import GroupParty, Party, UserParty
from previewit.domain.rounds import DEFAULT_ANONYMITY, InvalidRound, RoundId, TaskId
from previewit.domain.tenancy import SpaceId


def parse_when(value: str) -> datetime | None:
    """`datetime-local` input, read as UTC."""
    value = value.strip()
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M").replace(tzinfo=UTC)
    except ValueError:
        raise InvalidRound("Use a date and time like 2026-12-31 23:59.") from None


def whole(value: str, default: int) -> int:
    value = value.strip()
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        raise InvalidRound("The number of reviews must be a whole number.") from None


def parse_party(value: str) -> Party:
    """`user:<id>` or `group:<id>`, as the manual-pairing form sends it."""
    kind, _, ident = value.partition(":")
    if kind == "user" and ident:
        return UserParty(ident)
    if kind == "group" and ident:
        return GroupParty(ident)
    raise InvalidRound("Choose who should review.")


def build_rounds_router(*, rounds: RoundsService, calls: CallsService, kit: WebKit) -> APIRouter:
    router = APIRouter()
    run = run_in_threadpool

    def page(
        request: Request,
        user: User,
        call_id: str,
        *,
        error: str | None = None,
        notice: str | None = None,
        status: int = 200,
    ) -> Response:
        call_view = calls.call_view(user.id, CallId(call_id))
        call = call_view.call
        views = rounds.rounds(user.id, CallId(call_id))
        options = {v.round.id: rounds.reviewer_options(user.id, v.round.id) for v in views}
        return kit.render(
            request,
            "rounds.html",
            {
                "page_title": f"Rounds: {call.title}",
                "call": call,
                "views": views,
                "strategies": rounds.strategies(),
                "anonymity_options": rounds.anonymity_options(),
                "default_anonymity": DEFAULT_ANONYMITY,
                "options": options,
                "submissions": call_view.everyone or [],
                "next_number": len(views) + 1,
                "error": error,
                "notice": notice,
            },
            status,
        )

    def reviews_page(request: Request, user: User, space_id: str) -> Response:
        sid = SpaceId(space_id)
        tasks = rounds.my_tasks(user.id, sid)
        return kit.render(
            request,
            "my_reviews.html",
            {"page_title": "My reviews", "space_id": space_id, "tasks": tasks},
        )

    @router.get("/calls/{call_id}/rounds", response_class=HTMLResponse)
    async def rounds_page(request: Request, call_id: str) -> Response:
        return await run(page, request, current_user(request), call_id)

    @router.get("/spaces/{space_id}/reviews", response_class=HTMLResponse)
    async def my_reviews(request: Request, space_id: str) -> Response:
        return await run(reviews_page, request, current_user(request), space_id)

    async def act(
        request: Request,
        call_id: str,
        action: Callable[[User, FormData], str | None],
    ) -> Response:
        """CSRF, run `action(user, form)`, then show the call's rounds again."""
        form = await kit.checked_form(request)
        if form is None:
            return kit.forbidden()
        user = current_user(request)
        try:
            notice = await run(action, user, form)
        except (InvalidRound, UnknownStrategy) as e:
            message = "Choose an allocation method." if isinstance(e, UnknownStrategy) else str(e)
            return await run(page, request, user, call_id, error=message, status=400)
        if notice:
            return await run(page, request, user, call_id, notice=notice)
        return RedirectResponse(f"/calls/{call_id}/rounds", status_code=303)

    def settings(f: FormData) -> dict[str, Any]:
        return {
            "per_submission": whole(kit.text(f, "per_submission"), 1),
            "strategy_key": kit.text(f, "strategy"),
            "anonymity_key": kit.text(f, "anonymity") or DEFAULT_ANONYMITY,
            "opens_at": parse_when(kit.text(f, "opens_at")),
            "closes_at": parse_when(kit.text(f, "closes_at")),
        }

    @router.post("/calls/{call_id}/rounds")
    async def create_round(request: Request, call_id: str) -> Response:
        def action(user: User, f: FormData) -> None:
            rounds.create_round(user.id, CallId(call_id), **settings(f))

        return await act(request, call_id, action)

    @router.post("/rounds/{round_id}/edit")
    async def edit_round(request: Request, round_id: str) -> Response:
        user = current_user(request)
        call_id = await run(call_of_sync, user, round_id)

        def action(u: User, f: FormData) -> None:
            rounds.update_round(u.id, RoundId(round_id), **settings(f))

        return await act(request, call_id, action)

    def call_of_sync(user: User, round_id: str) -> str:
        return str(rounds.round_view(user.id, RoundId(round_id)).round.call_id)

    @router.post("/rounds/{round_id}/delete")
    async def delete_round(request: Request, round_id: str) -> Response:
        call_id = await run(call_of_sync, current_user(request), round_id)
        return await act(
            request, call_id, lambda u, _f: rounds.delete_round(u.id, RoundId(round_id))
        )

    @router.post("/rounds/{round_id}/allocate")
    async def allocate(request: Request, round_id: str) -> Response:
        call_id = await run(call_of_sync, current_user(request), round_id)

        def action(u: User, _f: FormData) -> str:
            report = rounds.allocate(u.id, RoundId(round_id))
            note = f"Allocated {report.created} review{'' if report.created == 1 else 's'}."
            if report.gaps:
                note += f" {len(report.gaps)} submission(s) have fewer reviewers than asked for."
            return note

        return await act(request, call_id, action)

    @router.post("/rounds/{round_id}/tasks")
    async def add_task(request: Request, round_id: str) -> Response:
        call_id = await run(call_of_sync, current_user(request), round_id)

        def action(u: User, f: FormData) -> None:
            rounds.add_task(
                u.id,
                RoundId(round_id),
                SubmissionId(kit.text(f, "submission_id")),
                parse_party(kit.text(f, "reviewer")),
            )

        return await act(request, call_id, action)

    @router.post("/rounds/{round_id}/tasks/{task_id}/delete")
    async def remove_task(request: Request, round_id: str, task_id: str) -> Response:
        call_id = await run(call_of_sync, current_user(request), round_id)
        return await act(request, call_id, lambda u, _f: rounds.remove_task(u.id, TaskId(task_id)))

    return router
