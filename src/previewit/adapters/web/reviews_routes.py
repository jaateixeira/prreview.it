"""The review workspace: the artifact beside the rubric form, autosave, pinned comments."""

from __future__ import annotations

from collections.abc import Mapping

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import FormData
from starlette.responses import Response

from previewit.adapters.web.kit import WebKit
from previewit.adapters.web.tenancy_routes import current_user
from previewit.application.reviews import AnswerErrors, ReviewsService
from previewit.domain.identity import User
from previewit.domain.reviews import AnnotationId, EditConflict, InvalidReview
from previewit.domain.rounds import TaskId

FIELD_PREFIX = "criterion-"


def answers_of(form: FormData) -> dict[str, str]:
    """The rubric answers in a submitted form: fields named `criterion-<id>`."""
    found: dict[str, str] = {}
    for key, value in form.multi_items():
        if key.startswith(FIELD_PREFIX) and isinstance(value, str):
            found[key[len(FIELD_PREFIX) :]] = value
    return found


def version_of(form: FormData) -> int:
    try:
        return int(str(form.get("version", "0")))
    except ValueError:
        return -1  # never matches a stored version, so it is reported as a conflict


def build_reviews_router(*, reviews: ReviewsService, kit: WebKit) -> APIRouter:
    router = APIRouter()
    run = run_in_threadpool

    def page(
        request: Request,
        user: User,
        task_id: str,
        *,
        draft: Mapping[str, str] | None = None,
        errors: Mapping[str, str] | None = None,
        error: str | None = None,
        notice: str | None = None,
        status: int = 200,
    ) -> Response:
        ws = reviews.workspace(user.id, TaskId(task_id), draft=draft, errors=errors)
        return kit.render(
            request,
            "workspace.html",
            {
                "page_title": f"Review: {ws.submission.title}",
                "ws": ws,
                "error": error,
                "notice": notice,
            },
            status,
        )

    @router.get("/tasks/{task_id}", response_class=HTMLResponse)
    async def workspace(request: Request, task_id: str) -> Response:
        notice = "Saved." if request.query_params.get("saved") else None
        if request.query_params.get("submitted"):
            notice = "Review submitted. You can still change it until the round closes."
        return await run(page, request, current_user(request), task_id, notice=notice)

    @router.get("/tasks/{task_id}/raw")
    async def raw(request: Request, task_id: str) -> Response:
        user = current_user(request)
        revision = await run(reviews.raw, user.id, TaskId(task_id))
        artifact = revision.artifact
        return Response(
            artifact.content,
            media_type=artifact.media_type,
            headers={
                "X-Content-Type-Options": "nosniff",
                "Content-Disposition": 'inline; filename="work"',
                "Cache-Control": "private, no-store",
            },
        )

    @router.post("/tasks/{task_id}")
    async def save(request: Request, task_id: str) -> Response:
        form = await kit.checked_form(request)
        if form is None:
            return kit.forbidden()
        user = current_user(request)
        answers = answers_of(form)
        submit = kit.text(form, "intent") == "submit"
        try:
            await run(
                reviews.save, user.id, TaskId(task_id), answers, version_of(form), submit=submit
            )
        except AnswerErrors as e:
            return await run(
                page, request, user, task_id, draft=answers, errors=e.problems, status=400,
                error="Some answers need fixing.",
            )  # fmt: skip
        except InvalidReview as e:
            return await run(page, request, user, task_id, draft=answers, error=str(e), status=400)
        except EditConflict:
            message = (
                "Someone else saved this review while you were editing. Your answers are shown "
                "below; check them and save again to replace theirs."
            )
            return await run(page, request, user, task_id, draft=answers, error=message, status=409)
        suffix = "submitted=1" if submit else "saved=1"
        return RedirectResponse(f"/tasks/{task_id}?{suffix}", status_code=303)

    @router.post("/tasks/{task_id}/autosave", response_class=HTMLResponse)
    async def autosave(request: Request, task_id: str) -> Response:
        """Called by the page as the reviewer types. Always answers 200 with a small status
        fragment (and the new version number), so the page can show what happened."""
        form = await kit.checked_form(request)
        if form is None:
            return kit.forbidden()
        user = current_user(request)
        try:
            review = await run(
                reviews.save, user.id, TaskId(task_id), answers_of(form), version_of(form)
            )
        except AnswerErrors as e:
            return _status(request, "Not saved yet: " + " ".join(e.problems.values()), None, True)
        except InvalidReview as e:
            return _status(request, f"Not saved yet: {e}", None, True)
        except EditConflict:
            return _status(
                request,
                "Not saved: someone changed this review. Reload the page to see their changes.",
                None,
                True,
            )
        return _status(request, "Saved", review.version, False)

    def _status(request: Request, message: str, version: int | None, problem: bool) -> Response:
        return kit.render(
            request,
            "_autosave_status.html",
            {"message": message, "version": version, "problem": problem},
        )

    @router.post("/tasks/{task_id}/annotations")
    async def add_annotation(request: Request, task_id: str) -> Response:
        form = await kit.checked_form(request)
        if form is None:
            return kit.forbidden()
        user = current_user(request)
        selector = {k: kit.text(form, k) for k in ("quote", "start", "end")}
        try:
            await run(
                reviews.add_annotation, user.id, TaskId(task_id), selector, kit.text(form, "body")
            )
        except InvalidReview as e:
            return await run(page, request, user, task_id, error=str(e), status=400)
        return RedirectResponse(f"/tasks/{task_id}#comments", status_code=303)

    @router.post("/tasks/{task_id}/annotations/{annotation_id}/delete")
    async def delete_annotation(request: Request, task_id: str, annotation_id: str) -> Response:
        form = await kit.checked_form(request)
        if form is None:
            return kit.forbidden()
        user = current_user(request)
        await run(reviews.delete_annotation, user.id, TaskId(task_id), AnnotationId(annotation_id))
        return RedirectResponse(f"/tasks/{task_id}#comments", status_code=303)

    return router
