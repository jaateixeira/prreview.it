"""Login, sign-up, logout, account and external-provider routes."""

from __future__ import annotations

import logging
from collections.abc import Mapping

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import FormData

from previewit.adapters.auth.base import AuthFailed, ExternalProvider
from previewit.adapters.settings import Settings
from previewit.adapters.web.session import (
    SessionCodec,
    clear_session_cookie,
    csrf_ok,
    csrf_token_for,
    safe_next,
    set_csrf_cookie,
    set_session_cookie,
)
from previewit.application.auth import (
    AuthService,
    EmailTaken,
    InvalidCredentials,
    WeakPassword,
)
from previewit.application.ports import MailError
from previewit.application.verification import SendResult, VerificationService
from previewit.domain.identity import InvalidEmail, Provider, User

log = logging.getLogger(__name__)

PROVIDER_LABELS = {
    Provider.GOOGLE: "Google",
    Provider.APPLE: "Apple",
    Provider.HAKA: "Haka (Finnish universities)",
}


def build_auth_router(
    *,
    auth: AuthService,
    verification: VerificationService,
    providers: Mapping[Provider, ExternalProvider],
    settings: Settings,
    templates: Jinja2Templates,
    codec: SessionCodec,
) -> APIRouter:
    router = APIRouter()

    def render(request: Request, name: str, context: dict[str, object], status: int = 200):
        token, new = csrf_token_for(request)
        context = {
            "csrf_token": token,
            "providers": [(p.value, PROVIDER_LABELS[p]) for p in providers],
            **context,
        }
        response = templates.TemplateResponse(request, name, context, status_code=status)
        if new:
            set_csrf_cookie(response, token, secure=settings.https)
        return response

    def logged_in(user: User, next_url: str) -> Response:
        response = RedirectResponse(next_url, status_code=303)
        set_session_cookie(response, codec.dumps(user.id), secure=settings.https)
        return response

    async def checked_form(request: Request) -> FormData | None:
        form = await request.form()
        submitted = form.get("csrf")
        if csrf_ok(request, submitted if isinstance(submitted, str) else None, settings.origin):
            return form
        return None

    def forbidden() -> Response:
        return HTMLResponse("Invalid or missing form token. Reload the page and try again.", 403)

    def text(form: FormData, key: str) -> str:
        value = form.get(key)
        return value if isinstance(value, str) else ""

    # -- pages ---------------------------------------------------------------

    @router.get("/login", response_class=HTMLResponse)
    async def login_page(request: Request, next: str = "/") -> Response:
        return render(request, "login.html", {"page_title": "Log in", "next": safe_next(next)})

    @router.post("/login")
    async def login(request: Request) -> Response:
        form = await checked_form(request)
        if form is None:
            return forbidden()
        next_url = safe_next(text(form, "next"))
        try:
            user = await run_in_threadpool(
                auth.login_with_password, text(form, "email"), text(form, "password")
            )
        except InvalidCredentials:
            return render(
                request,
                "login.html",
                {
                    "page_title": "Log in",
                    "next": next_url,
                    "email": text(form, "email"),
                    "error": "Wrong email or password.",
                },
                status=400,
            )
        return logged_in(user, next_url)

    @router.get("/signup", response_class=HTMLResponse)
    async def signup_page(request: Request, next: str = "/") -> Response:
        return render(request, "signup.html", {"page_title": "Sign up", "next": safe_next(next)})

    @router.post("/signup")
    async def signup(request: Request) -> Response:
        form = await checked_form(request)
        if form is None:
            return forbidden()
        next_url = safe_next(text(form, "next"))
        try:
            user = await run_in_threadpool(
                auth.register_with_password,
                text(form, "email"),
                text(form, "password"),
                text(form, "name"),
            )
        except InvalidEmail:
            error = "That does not look like an email address."
        except WeakPassword as weak:
            error = (
                "Use at least 10 characters."
                if weak.problem == "too_short"
                else "That password is too long (128 characters at most)."
            )
        except EmailTaken:
            error = "An account with this email already exists. Log in instead."
        else:
            await send_verification(user)
            return logged_in(user, next_url)
        return render(
            request,
            "signup.html",
            {
                "page_title": "Sign up",
                "next": next_url,
                "email": text(form, "email"),
                "name": text(form, "name"),
                "error": error,
            },
            status=400,
        )

    @router.post("/logout")
    async def logout(request: Request) -> Response:
        if await checked_form(request) is None:
            return forbidden()
        response = RedirectResponse("/", status_code=303)
        clear_session_cookie(response)
        return response

    async def send_verification(user: User) -> SendResult | None:
        try:
            return await run_in_threadpool(verification.send, user)
        except (MailError, OSError):
            log.warning("could not send verification mail", exc_info=True)
            return None

    def account_page(request: Request, user: User, notice: str | None = None) -> Response:
        linked = sorted(PROVIDER_LABELS[k.provider] for k in user.identities)
        return render(
            request,
            "account.html",
            {"page_title": "Your account", "account": user, "linked": linked, "notice": notice},
        )

    @router.get("/verify", response_class=HTMLResponse)
    async def verify_page(request: Request, token: str = "") -> Response:
        # GET never consumes the token: mail scanners and prefetchers open links.
        return render(request, "verify.html", {"page_title": "Confirm your email", "token": token})

    @router.post("/verify")
    async def verify(request: Request) -> Response:
        form = await checked_form(request)
        if form is None:
            return forbidden()
        confirmed = await run_in_threadpool(verification.confirm, text(form, "token"))
        if confirmed is None:
            return render(
                request,
                "verify.html",
                {
                    "page_title": "Confirm your email",
                    "token": "",
                    "error": "This link is invalid or has expired. Log in and request a new one.",
                },
                status=400,
            )
        return render(request, "verify.html", {"page_title": "Email confirmed", "done": True})

    @router.post("/account/verify/resend")
    async def resend(request: Request) -> Response:
        if await checked_form(request) is None:
            return forbidden()
        user: User | None = request.state.user
        if user is None:
            return RedirectResponse("/login?next=%2Faccount", status_code=303)
        result = await send_verification(user)
        notice = {
            SendResult.SENT: "Verification email sent. Check your inbox.",
            SendResult.TOO_SOON: "Please wait a minute before asking for another email.",
            SendResult.ALREADY_VERIFIED: "Your email is already verified.",
            SendResult.NO_EMAIL: "Your account has no email address to verify.",
            None: "We could not send the email right now. Try again later.",
        }[result]
        return account_page(request, user, notice)

    @router.get("/account", response_class=HTMLResponse)
    async def account(request: Request) -> Response:
        user: User | None = request.state.user
        if user is None:
            return RedirectResponse("/login?next=%2Faccount", status_code=303)
        return account_page(request, user)

    def failed_login(request: Request, name: str, next_url: str) -> Response:
        request.session.clear()
        label = PROVIDER_LABELS[Provider(name)]
        return render(
            request,
            "login.html",
            {
                "page_title": "Log in",
                "next": next_url,
                "error": f"Signing in with {label} could not be completed. Please try again.",
            },
            status=400,
        )

    # -- external providers ----------------------------------------------------

    def provider_or_404(name: str) -> ExternalProvider | None:
        try:
            return providers.get(Provider(name))
        except ValueError:
            return None

    @router.get("/auth/{name}/login")
    async def external_login(request: Request, name: str, next: str = "/") -> Response:
        provider = provider_or_404(name)
        if provider is None:
            return HTMLResponse("Unknown sign-in provider.", 404)
        # A discovery-service round trip re-enters here without `next`: keep the first one.
        if "next" in request.query_params or "next" not in request.session:
            request.session["next"] = safe_next(next)
        try:
            return await provider.begin(request, f"{settings.origin}/auth/{name}/callback")
        except AuthFailed:
            return failed_login(request, name, safe_next(request.session.get("next")))

    @router.get("/auth/{name}/metadata")
    async def provider_metadata(name: str) -> Response:
        provider = provider_or_404(name)
        publish = getattr(provider, "metadata_xml", None)
        if publish is None:
            return HTMLResponse("No metadata for this provider.", 404)
        xml = await run_in_threadpool(publish)
        return Response(xml, media_type="application/samlmetadata+xml")

    async def external_callback(request: Request, name: str) -> Response:
        provider = provider_or_404(name)
        if provider is None:
            return HTMLResponse("Unknown sign-in provider.", 404)
        next_url = safe_next(request.session.get("next"))
        try:
            claims = await provider.complete(request)
        except AuthFailed:
            return failed_login(request, name, next_url)
        request.session.clear()
        user = await run_in_threadpool(auth.login_with_external, claims)
        return logged_in(user, next_url)

    router.add_api_route("/auth/{name}/callback", external_callback, methods=["GET", "POST"])
    return router
