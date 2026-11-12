"""FastAPI application factory for the web adapter."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool
from starlette.middleware.sessions import SessionMiddleware

from previewit.adapters.auth.base import ExternalProvider
from previewit.adapters.settings import Settings
from previewit.adapters.web.auth_routes import build_auth_router
from previewit.adapters.web.session import SESSION_COOKIE, SessionCodec
from previewit.application.auth import AuthService
from previewit.domain.identity import Provider

HERE = Path(__file__).parent

# AGPL-3.0 section 13: users of a network service must be offered the source.
SOURCE_URL = "https://github.com/jaateixeira/prreview.it"


def build_app(
    settings: Settings,
    auth: AuthService,
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
            auth=auth, providers=providers, settings=settings, templates=templates, codec=codec
        )
    )

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
