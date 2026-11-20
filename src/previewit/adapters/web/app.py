"""FastAPI application factory for the web adapter."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from loguru import logger
from starlette.concurrency import run_in_threadpool
from starlette.middleware.sessions import SessionMiddleware

from previewit.adapters.auth.base import ExternalProvider
from previewit.adapters.mcp import McpServer
from previewit.adapters.payments.paddle import PaddleNotifications
from previewit.adapters.settings import Settings
from previewit.adapters.web import local_time
from previewit.adapters.web.ai_routes import build_ai_router, usd
from previewit.adapters.web.auth_routes import build_auth_router
from previewit.adapters.web.calls_routes import build_calls_router
from previewit.adapters.web.docs_routes import build_docs_router
from previewit.adapters.web.invitations_routes import build_invitations_router
from previewit.adapters.web.kit import WebKit
from previewit.adapters.web.limits import RateLimiter
from previewit.adapters.web.mcp_routes import build_mcp_router
from previewit.adapters.web.money_routes import Seller, build_money_router, paddle_checkout
from previewit.adapters.web.pages_routes import build_pages_router
from previewit.adapters.web.quick_review_routes import build_quick_review_router
from previewit.adapters.web.reviews_routes import build_reviews_router
from previewit.adapters.web.rounds_routes import build_rounds_router
from previewit.adapters.web.rubrics_routes import build_rubrics_router
from previewit.adapters.web.session import SESSION_COOKIE, SessionCodec
from previewit.adapters.web.tenancy_routes import LoginRequired, build_tenancy_router
from previewit.application.ai_reviews import AiReviewsService
from previewit.application.auth import AuthService
from previewit.application.calls import CallsService, InvalidShare
from previewit.application.credits import CreditsService
from previewit.application.invitations import (
    InvalidInvitationLink,
    InvitationsService,
    WrongEmail,
)
from previewit.application.prepared_requests import PreparedRequestsService
from previewit.application.quick_review import QuickReviewService
from previewit.application.reviews import ReviewsService
from previewit.application.rounds import RoundsService
from previewit.application.rubrics import RubricsService
from previewit.application.tenancy import (
    Forbidden,
    InvalidInvite,
    NotFound,
    TenancyService,
    VerificationRequired,
)
from previewit.application.verification import VerificationService
from previewit.application.web_pages import PageChecker
from previewit.domain.ai_models import flag
from previewit.domain.credits import euros
from previewit.domain.identity import Provider

HERE = Path(__file__).parent

# AGPL-3.0 section 13: users of a network service must be offered the source.
SOURCE_URL = "https://github.com/jaateixeira/prreview.it"


CLEANUP_SECONDS = 300.0  # how often forms kept for visitors and expired requests are deleted


async def forget_expired_forever(prepared: PreparedRequestsService) -> None:
    """Delete expired prepared requests and the files kept with them (ADR 0024), every few
    minutes, so a visitor's file is gone soon after its hour even if nobody asks for it."""
    while True:
        await asyncio.sleep(CLEANUP_SECONDS)
        try:
            await run_in_threadpool(prepared.forget_expired)
        except Exception:  # a bad moment for the database must not stop the loop
            logger.exception("Could not delete expired prepared requests")


def build_app(
    settings: Settings,
    auth: AuthService,
    verification: VerificationService,
    tenancy: TenancyService,
    calls: CallsService,
    rubrics: RubricsService,
    rounds: RoundsService,
    reviews: ReviewsService,
    invitations: InvitationsService,
    quick: QuickReviewService,
    providers: Mapping[Provider, ExternalProvider],
    *,
    pages: PageChecker,
    prepared: PreparedRequestsService,
    version: str = "dev",
    ai: AiReviewsService | None = None,
    credits: CreditsService | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        cleanup = asyncio.create_task(forget_expired_forever(prepared))
        try:
            yield
        finally:
            cleanup.cancel()

    app = FastAPI(title="Previewit", docs_url=None, redoc_url=None, lifespan=lifespan)
    templates = Jinja2Templates(directory=HERE / "templates")
    templates.env.globals["source_url"] = SOURCE_URL
    templates.env.globals["site_host"] = settings.host
    templates.env.globals["ai_on"] = ai is not None  # AI reviews (ADR 0025)
    templates.env.globals["flag"] = flag
    templates.env.filters["usd"] = usd
    templates.env.filters["euros"] = euros
    templates.env.globals["seller"] = Seller.from_settings(settings)  # ADR 0026
    local_time.install(templates.env)
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
    codec = SessionCodec(settings.secret_key)
    alias_hosts = settings.alias_hosts

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

    @app.middleware("http")
    async def keep_tokens_out_of_referrers(request: Request, call_next):
        response = await call_next(request)
        secret_in_path = ("/s/", "/join/", "/i/", "/prepared/")
        if request.url.path.startswith(secret_in_path):
            response.headers["Referrer-Policy"] = "same-origin"  # never to other sites
        return response

    @app.middleware("http")
    async def one_address(request: Request, call_next):
        """A request that came in under an alias is sent to the same page at the main address.

        Added last so it runs first: nothing is looked up or processed under the other name,
        and forms, cookies and login callbacks only ever see one origin.
        """
        if request.headers.get("host", "").lower() in alias_hosts:
            raw = request.scope.get("raw_path")
            path = raw.decode("latin-1") if raw else quote(request.url.path)
            query = f"?{request.url.query}" if request.url.query else ""
            return RedirectResponse(
                f"{settings.origin}{path}{query}",
                status_code=308,
                headers={"Referrer-Policy": "same-origin"},  # the path may hold a token
            )
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
    app.include_router(build_docs_router())
    app.include_router(build_tenancy_router(tenancy=tenancy, kit=kit))
    app.include_router(build_calls_router(calls=calls, rubrics=rubrics, kit=kit))
    app.include_router(build_rubrics_router(rubrics=rubrics, kit=kit))
    app.include_router(
        build_rounds_router(rounds=rounds, calls=calls, invitations=invitations, kit=kit)
    )
    app.include_router(
        build_invitations_router(
            invitations=invitations, kit=kit, auth=auth, verification=verification, codec=codec
        )
    )
    app.include_router(build_reviews_router(reviews=reviews, kit=kit))
    app.include_router(
        build_quick_review_router(
            quick=quick,
            kit=kit,
            pages=pages,
            prepared=prepared,
            visitors=RateLimiter(10, 600),  # forms kept per client address (ADR 0024)
            ai=ai,
        )
    )
    if ai is not None:
        app.include_router(
            build_ai_router(ai=ai, kit=kit, visitors=RateLimiter(20, 600))  # per client address
        )
    checkout = paddle_checkout(settings)
    secret = settings.paddle_webhook_secret
    app.include_router(
        build_money_router(
            kit=kit,
            credits=credits,
            ai=ai,
            notifications=PaddleNotifications(credits, secret) if credits and secret else None,
            checkout=checkout,
        )
    )
    mcp = McpServer(
        prepared=prepared,
        origin=settings.origin,
        version=version,
        allow=RateLimiter(20, 600).allow,  # prepared requests per client address
    )
    app.include_router(build_mcp_router(server=mcp, kit=kit))
    app.include_router(
        build_pages_router(pages=pages, kit=kit, limiter=RateLimiter(30, 60))  # per person
    )

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

    @app.exception_handler(VerificationRequired)
    async def verification_required(request: Request, _exc: Exception):
        return error_page(
            request,
            403,
            "Verify your email first",
            "This site requires a verified email address for that. "
            "Open your account page to verify yours, then try again.",
        )

    @app.exception_handler(InvalidInvite)
    async def invalid_invite(request: Request, _exc: Exception):
        return error_page(
            request,
            404,
            "Invitation not valid",
            "This invitation link is invalid, expired or has been used up. Ask for a new one.",
        )

    @app.exception_handler(InvalidShare)
    async def invalid_share(request: Request, _exc: Exception):
        return error_page(
            request,
            404,
            "Link not valid",
            "This share link is invalid, expired or has been withdrawn. Ask for a new one.",
        )

    @app.exception_handler(InvalidInvitationLink)
    async def invalid_invitation(request: Request, _exc: Exception):
        return error_page(
            request,
            404,
            "Invitation not valid",
            "This invitation is invalid, expired, withdrawn or its round has closed. "
            "Ask the organizer for a new one.",
        )

    @app.exception_handler(WrongEmail)
    async def wrong_email(request: Request, exc: Exception):
        hint = exc.hint if isinstance(exc, WrongEmail) else ""
        return error_page(
            request,
            403,
            "This invitation is for another address",
            f"It was sent to {hint}. Log out and sign in with that email address to open it.",
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
