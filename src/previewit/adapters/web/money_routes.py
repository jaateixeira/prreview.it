"""Pricing, the legal pages Paddle reviews, the Credit page and Paddle's notifications
(ADR 0026).

The public pages need no account: Paddle's domain review reads them, and so does anyone
deciding whether to buy. What they say about the seller comes from the `[seller]` settings,
because a self-hosted Previewit is sold, if at all, by someone else.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool
from starlette.responses import Response

from previewit.adapters.entitlements import FREE_AI_REVIEWS_PER_DAY
from previewit.adapters.payments.paddle import PaddleNotifications
from previewit.adapters.settings import Settings
from previewit.adapters.web.kit import WebKit
from previewit.adapters.web.tenancy_routes import current_user
from previewit.application.ai_reviews import AiReviewsService
from previewit.application.credits import CreditsService
from previewit.domain.ai_models import estimate, tokens_for
from previewit.domain.identity import User

LEGAL_UPDATED = "20 November 2026"
ESSAY_CHARS = 30_000  # about 5,000 words: the example on the pricing page
MAX_NOTIFICATION_BYTES = 1_000_000
BUYER_TERMS = "https://www.paddle.com/legal/buyer-terms"


@dataclass(frozen=True)
class Seller:
    """Who runs and sells this Previewit, from the `[seller]` settings."""

    legal_name: str
    trading_name: str
    business_id: str
    address: str
    email: str
    phone: str
    privacy_email: str
    processors: tuple[str, ...]

    @property
    def complete(self) -> bool:
        return bool(self.legal_name and self.address and self.email)

    @classmethod
    def from_settings(cls, settings: Settings) -> Seller:
        email = settings.seller_email or ""
        return cls(
            legal_name=settings.seller_legal_name or "",
            trading_name=settings.seller_trading_name,
            business_id=settings.seller_business_id or "",
            address=settings.seller_address or "",
            email=email,
            phone=settings.seller_phone or "",
            privacy_email=settings.seller_privacy_email or email,
            processors=settings.seller_processors,
        )


@dataclass(frozen=True)
class PaddleCheckout:
    """What the browser needs to open Paddle's checkout. The client-side token is public."""

    environment: str
    token: str


def paddle_checkout(settings: Settings) -> PaddleCheckout | None:
    if not (settings.paddle_client_token and settings.paddle_webhook_secret):
        return None
    return PaddleCheckout(settings.paddle_environment, settings.paddle_client_token)


def build_money_router(
    *,
    kit: WebKit,
    credits: CreditsService | None,
    ai: AiReviewsService | None,
    notifications: PaddleNotifications | None,
    checkout: PaddleCheckout | None,
) -> APIRouter:
    router = APIRouter()
    selling = credits is not None and checkout is not None and bool(credits.packs)

    def page(request: Request, name: str, title: str, extra: dict[str, Any] | None = None):
        context = {"page_title": title, "updated": LEGAL_UPDATED, "buyer_terms": BUYER_TERMS}
        return kit.render(request, name, {**context, **(extra or {})})

    @router.get("/pricing", response_class=HTMLResponse)
    async def pricing(request: Request) -> Response:
        examples = []
        if ai is not None:
            tokens = tokens_for(ESSAY_CHARS)
            for card in await run_in_threadpool(ai.cards):
                if card.free or ai.credit_for(card):
                    examples.append((card, estimate(card, tokens, ai.pricing)))
        return page(
            request,
            "pricing.html",
            "Pricing",
            {
                "packs": credits.packs if credits is not None and selling else (),
                "examples": examples[:8],
                "free_ai_per_day": FREE_AI_REVIEWS_PER_DAY,
                "checkout": checkout,
                "ai_on": ai is not None,
            },
        )

    @router.get("/terms", response_class=HTMLResponse)
    async def terms(request: Request) -> Response:
        return page(request, "terms.html", "Terms and conditions")

    @router.get("/refunds", response_class=HTMLResponse)
    async def refunds(request: Request) -> Response:
        return page(request, "refunds.html", "Refund policy")

    @router.get("/privacy", response_class=HTMLResponse)
    async def privacy(request: Request) -> Response:
        return page(request, "privacy.html", "Privacy notice")

    @router.get("/contact", response_class=HTMLResponse)
    async def contact(request: Request) -> Response:
        return page(request, "contact.html", "Contact")

    @router.get("/credit", response_class=HTMLResponse)
    async def credit(request: Request) -> Response:
        user: User | None = request.state.user
        if user is None:
            return RedirectResponse("/login?next=%2Fcredit", status_code=303)
        if user.is_guest:
            return RedirectResponse("/account/new", status_code=303)
        me = current_user(request)
        balance = await run_in_threadpool(credits.balance, me.id) if credits else 0
        history = await run_in_threadpool(credits.history, me.id) if credits else []
        return page(
            request,
            "credit.html",
            "Credit",
            {
                "balance": balance,
                "history": history,
                "packs": credits.packs if credits is not None and selling else (),
                "checkout": checkout if selling else None,
                "buyer": me,
                "success_url": f"{kit.settings.origin}/credit?bought=1",
                "bought": request.query_params.get("bought") == "1",
            },
        )

    @router.post("/paddle/webhook")
    async def paddle_webhook(request: Request) -> Response:
        """Paddle's notifications. Not a form: no form token; Paddle's signature instead."""
        if notifications is None:
            return PlainTextResponse("not configured", 404)
        body = await request.body()
        if len(body) > MAX_NOTIFICATION_BYTES:
            return PlainTextResponse("too large", 413)
        header = request.headers.get("paddle-signature", "")
        status = await run_in_threadpool(notifications.handle, header, body)
        return PlainTextResponse("ok" if status == 200 else "refused", status)

    return router
