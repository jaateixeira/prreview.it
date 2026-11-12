"""Rubric library, criteria builder and attaching a rubric to a call."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import FormData
from starlette.responses import Response

from previewit.adapters.web.kit import WebKit
from previewit.adapters.web.tenancy_routes import current_user
from previewit.application.criteria import CriterionError, CriterionType, UnknownCriterionType
from previewit.application.rubrics import RubricInUse, RubricsService
from previewit.domain.calls import CallId
from previewit.domain.identity import User
from previewit.domain.rubrics import CriterionId, InvalidRubric, RubricId
from previewit.domain.tenancy import SpaceId


def raw_config(form: FormData, kind: CriterionType) -> dict[str, str]:
    """The settings a criterion type asked for, sent by the form as `cfg_<name>`."""
    result: dict[str, str] = {}
    for field in kind.fields:
        value = form.get(f"cfg_{field.name}")
        result[field.name] = value if isinstance(value, str) else ""
    return result


def whole_number(value: str, default: int) -> int:
    value = value.strip()
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        raise InvalidRubric("Weights must be whole numbers.") from None


def build_rubrics_router(*, rubrics: RubricsService, kit: WebKit) -> APIRouter:
    router = APIRouter()
    run = run_in_threadpool

    def library(
        request: Request, user: User, space_id: str, error: str | None = None, status: int = 200
    ) -> Response:
        sid = SpaceId(space_id)
        found = rubrics.rubrics(user.id, sid)
        return kit.render(
            request,
            "rubrics.html",
            {
                "page_title": "Rubrics",
                "space_id": space_id,
                "rubrics": found,
                "templates": rubrics.templates(user.id, sid),
                "error": error,
            },
            status,
        )

    def builder(
        request: Request,
        user: User,
        rubric_id: str,
        error: str | None = None,
        status: int = 200,
    ) -> Response:
        view = rubrics.rubric_view(user.id, RubricId(rubric_id))
        types: list[CriterionType] = rubrics.criterion_types()
        return kit.render(
            request,
            "rubric.html",
            {
                "page_title": view.rubric.name,
                "view": view,
                "types": types,
                "type_by_key": {t.key: t for t in types},
                "error": error,
            },
            status,
        )

    # -- library -----------------------------------------------------------------------------

    @router.get("/spaces/{space_id}/rubrics", response_class=HTMLResponse)
    async def rubric_library(request: Request, space_id: str) -> Response:
        return await run(library, request, current_user(request), space_id)

    @router.post("/spaces/{space_id}/rubrics")
    async def create_rubric(request: Request, space_id: str) -> Response:
        form = await kit.checked_form(request)
        if form is None:
            return kit.forbidden()
        user = current_user(request)
        try:
            rubric = await run(
                lambda: rubrics.create_rubric(
                    user.id,
                    SpaceId(space_id),
                    kit.text(form, "name"),
                    kit.text(form, "description"),
                    kit.text(form, "template") or None,
                )
            )
        except InvalidRubric as e:
            message = str(e)
            return await run(library, request, user, space_id, message, 400)
        return RedirectResponse(f"/rubrics/{rubric.id}", status_code=303)

    @router.get("/rubrics/{rubric_id}", response_class=HTMLResponse)
    async def rubric_page(request: Request, rubric_id: str) -> Response:
        return await run(builder, request, current_user(request), rubric_id)

    async def act(request: Request, rubric_id: str, action: Any, back: str | None = None):
        """CSRF and login checks, run `action(user, form)`, redirect back to the builder."""
        form = await kit.checked_form(request)
        if form is None:
            return kit.forbidden()
        user = current_user(request)
        try:
            await run(action, user, form)
        except (InvalidRubric, CriterionError, UnknownCriterionType) as e:
            message = (
                "Choose a kind of question." if isinstance(e, UnknownCriterionType) else str(e)
            )
            return await run(builder, request, user, rubric_id, message, 400)
        except RubricInUse:
            message = "Calls use this rubric. Detach it from them first."
            return await run(builder, request, user, rubric_id, message, 400)
        return RedirectResponse(back or f"/rubrics/{rubric_id}", status_code=303)

    @router.post("/rubrics/{rubric_id}/edit")
    async def edit_rubric(request: Request, rubric_id: str) -> Response:
        return await act(
            request,
            rubric_id,
            lambda u, f: rubrics.update_rubric(
                u.id, RubricId(rubric_id), kit.text(f, "name"), kit.text(f, "description")
            ),
        )

    @router.post("/rubrics/{rubric_id}/delete")
    async def delete_rubric(request: Request, rubric_id: str) -> Response:
        user = current_user(request)
        space_id = (await run(rubrics.rubric_view, user.id, RubricId(rubric_id))).rubric.space_id
        return await act(
            request,
            rubric_id,
            lambda u, _f: rubrics.delete_rubric(u.id, RubricId(rubric_id)),
            back=f"/spaces/{space_id}/rubrics",
        )

    @router.post("/rubrics/{rubric_id}/duplicate")
    async def duplicate_rubric(request: Request, rubric_id: str) -> Response:
        form = await kit.checked_form(request)
        if form is None:
            return kit.forbidden()
        user = current_user(request)
        copy = await run(rubrics.duplicate_rubric, user.id, RubricId(rubric_id))
        return RedirectResponse(f"/rubrics/{copy.id}", status_code=303)

    # -- criteria ----------------------------------------------------------------------------

    def kind_of(key: str) -> CriterionType:
        return next((t for t in rubrics.criterion_types() if t.key == key), None) or _unknown(key)

    def _unknown(key: str) -> CriterionType:
        raise UnknownCriterionType(key)

    @router.post("/rubrics/{rubric_id}/criteria")
    async def add_criterion(request: Request, rubric_id: str) -> Response:
        def action(user: User, f: FormData) -> None:
            kind = kind_of(kit.text(f, "type_key"))
            rubrics.add_criterion(
                user.id,
                RubricId(rubric_id),
                type_key=kind.key,
                title=kit.text(f, "title"),
                guidance=kit.text(f, "guidance"),
                raw_config=raw_config(f, kind),
                weight=whole_number(kit.text(f, "weight"), 1),
                required=kit.text(f, "required") == "on",
            )

        return await act(request, rubric_id, action)

    @router.post("/rubrics/{rubric_id}/criteria/{criterion_id}/edit")
    async def edit_criterion(request: Request, rubric_id: str, criterion_id: str) -> Response:
        def action(user: User, f: FormData) -> None:
            kind = kind_of(kit.text(f, "type_key"))
            rubrics.update_criterion(
                user.id,
                RubricId(rubric_id),
                CriterionId(criterion_id),
                title=kit.text(f, "title"),
                guidance=kit.text(f, "guidance"),
                raw_config=raw_config(f, kind),
                weight=whole_number(kit.text(f, "weight"), 1),
                required=kit.text(f, "required") == "on",
            )

        return await act(request, rubric_id, action)

    @router.post("/rubrics/{rubric_id}/criteria/{criterion_id}/delete")
    async def delete_criterion(request: Request, rubric_id: str, criterion_id: str) -> Response:
        return await act(
            request,
            rubric_id,
            lambda u, _f: rubrics.delete_criterion(
                u.id, RubricId(rubric_id), CriterionId(criterion_id)
            ),
        )

    @router.post("/rubrics/{rubric_id}/criteria/{criterion_id}/move")
    async def move_criterion(request: Request, rubric_id: str, criterion_id: str) -> Response:
        return await act(
            request,
            rubric_id,
            lambda u, f: rubrics.move_criterion(
                u.id,
                RubricId(rubric_id),
                CriterionId(criterion_id),
                -1 if kit.text(f, "direction") == "up" else 1,
            ),
        )

    # -- calls -------------------------------------------------------------------------------

    @router.post("/calls/{call_id}/rubric")
    async def attach_rubric(request: Request, call_id: str) -> Response:
        form = await kit.checked_form(request)
        if form is None:
            return kit.forbidden()
        user = current_user(request)
        chosen = kit.text(form, "rubric_id")
        await run(rubrics.attach, user.id, CallId(call_id), RubricId(chosen) if chosen else None)
        return RedirectResponse(f"/calls/{call_id}", status_code=303)

    return router
