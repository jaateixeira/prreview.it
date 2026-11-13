"""Small helpers shared by the route modules: rendering, CSRF-checked forms."""

from __future__ import annotations

from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from starlette.datastructures import FormData
from starlette.requests import Request
from starlette.responses import Response

from previewit.adapters.settings import Settings
from previewit.adapters.web.session import (
    csrf_ok,
    csrf_token_for,
    set_csrf_cookie,
)


class WebKit:
    def __init__(self, templates: Jinja2Templates, settings: Settings) -> None:
        self.templates = templates
        self.settings = settings

    def render(
        self, request: Request, name: str, context: dict[str, object], status: int = 200
    ) -> Response:
        token, new = csrf_token_for(request)
        response = self.templates.TemplateResponse(
            request, name, {"csrf_token": token, **context}, status_code=status
        )
        if new:
            set_csrf_cookie(response, token, secure=self.settings.https)
        return response

    async def checked_form(self, request: Request) -> FormData | None:
        form = await request.form()
        submitted = form.get("csrf")
        if csrf_ok(
            request, submitted if isinstance(submitted, str) else None, self.settings.origin
        ):
            return form
        return None

    @staticmethod
    def forbidden() -> Response:
        return HTMLResponse("Invalid or missing form token. Reload the page and try again.", 403)

    @staticmethod
    def text(form: FormData, key: str) -> str:
        value = form.get(key)
        return value if isinstance(value, str) else ""

    @staticmethod
    def texts(form: FormData, key: str) -> list[str]:
        """Every text value sent under one name (a group of checkboxes)."""
        return [v for v in form.getlist(key) if isinstance(v, str)]
