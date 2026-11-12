"""FastAPI application factory for the web adapter."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool
from starlette.middleware.sessions import SessionMiddleware

from previewit.adapters.auth.base import ExternalProvider
from previewit.adapters.settings import Settings
from previewit.adapters.web.auth_routes import build_auth_router
from previewit.adapters.web.kit import WebKit
from previewit.adapters.web.session import SESSION_COOKIE, SessionCodec
from previewit.adapters.web.tenancy_routes import LoginRequired, build_tenancy_router
from previewit.application.auth import AuthService
from previewit.application.tenancy import (
    Forbidden,
    InvalidInvite,
    NotFound,
    TenancyService,
)
from previewit.application.verification import VerificationService
from previewit.domain.identity import Provider

HERE = Path(__file__).parent

# AGPL-3.0 section 13: users of a network service must be offered the source.
SOURCE_URL = "https://github.com/jaateixeira/prreview.it"


def build_app(
    settings: Settings,
    auth: AuthService,
    verification: VerificationService,
    tenancy: TenancyService,
    providers: Mapping[Provider, ExternalProvider],
) -> FastAPI:
    app = FastAPI(title="Previewit", docs_url=None, redoc_url=None)
    templates = Jinja2Templates(directory=HERE / "templates")
    templates.env.globals["source_url"] = SOURCE_URL
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
    codec = SessionCodec(settings.secret_key)

    # Short-lived state for OAuth/SAML round trips only. Apple and SAML return through a
    # cross-site POST, so in https deployments the cookie must be SameSite=None; Secure.
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key,
        session_cookie="pv_flow",
        path="/auth",
        max_age=600,
        same_site="none" if settings.https else "lax",
        https_only=settings.https,
    )

    @app.middleware("http")
    async def load_user(request: Request, call_next):
        request.state.user = None
        if not request.url.path.startswith("/static"):
            user_id = codec.loads(request.cookies.get(SESSION_COOKIE))
            if user_id is not None:
                request.state.user = await run_in_threadpool(auth.get_user, user_id)  # type: ignore[arg-type]
        return await call_next(request)

    app.include_router(
        build_auth_router(
            auth=auth,
            verification=verification,
            providers=providers,
            settings=settings,
            templates=templates,
            codec=codec,
        )
    )

    kit = WebKit(templates, settings)
    app.include_router(build_tenancy_router(tenancy=tenancy, kit=kit))

    def error_page(request: Request, status: int, title: str, message: str):
        return kit.render(
            request, "error.html", {"page_title": title, "title": title, "message": message}, status
        )

    @app.exception_handler(NotFound)
    async def not_found(request: Request, _exc: Exception):
        return error_page(request, 404, "Not found", "We could not find that page.")

    @app.exception_handler(Forbidden)
    async def forbidden(request: Request, _exc: Exception):
        return error_page(request, 403, "Not allowed", "You do not have permission to do that.")

    @app.exception_handler(InvalidInvite)
    async def invalid_invite(request: Request, _exc: Exception):
        return error_page(
            request,
            404,
            "Invitation not valid",
            "This invitation link is invalid, expired or has been used up. Ask for a new one.",
        )

    @app.exception_handler(LoginRequired)
    async def login_required(request: Request, _exc: Exception):
        next_url = request.url.path if request.method == "GET" else "/spaces"
        return RedirectResponse(f"/login?next={quote(next_url, safe='')}", status_code=303)

    @app.get("/", response_class=HTMLResponse)
    async def home(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(request, "home.html", {"page_title": "Previewit"})

    @app.get("/fragments/status", response_class=HTMLResponse)
    async def status_fragment(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(request, "fragments/status.html", {})

    @app.get("/healthz", response_class=PlainTextResponse)
    async def healthz() -> str:
        return "ok"

    return app
