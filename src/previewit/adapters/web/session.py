"""Signed session cookie, CSRF tokens and safe redirects."""

from __future__ import annotations

import hmac
import secrets

from itsdangerous import BadSignature, URLSafeTimedSerializer
from starlette.requests import Request
from starlette.responses import Response

SESSION_COOKIE = "pv_session"
CSRF_COOKIE = "pv_csrf"
SESSION_MAX_AGE = 14 * 24 * 3600


class SessionCodec:
    def __init__(self, secret_key: str, max_age: int = SESSION_MAX_AGE) -> None:
        self._serializer = URLSafeTimedSerializer(secret_key, salt="previewit-session")
        self._max_age = max_age

    def dumps(self, user_id: str) -> str:
        return self._serializer.dumps(user_id)

    def loads(self, token: str | None) -> str | None:
        if not token:
            return None
        try:
            value = self._serializer.loads(token, max_age=self._max_age)
        except BadSignature:
            return None
        return value if isinstance(value, str) else None


def set_session_cookie(response: Response, token: str, *, secure: bool) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=secure,
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")


def csrf_token_for(request: Request) -> tuple[str, bool]:
    """The request's CSRF token, and whether it is new (cookie must then be set)."""
    existing = request.cookies.get(CSRF_COOKIE)
    if existing:
        return existing, False
    return secrets.token_urlsafe(32), True


def set_csrf_cookie(response: Response, token: str, *, secure: bool) -> None:
    response.set_cookie(CSRF_COOKIE, token, httponly=True, samesite="lax", secure=secure, path="/")


def csrf_ok(request: Request, submitted: str | None, origin: str) -> bool:
    """Double-submit check plus an Origin check when the browser sends one."""
    cookie = request.cookies.get(CSRF_COOKIE)
    if not cookie or not submitted or not hmac.compare_digest(cookie, submitted):
        return False
    sent_origin = request.headers.get("origin")
    return sent_origin is None or sent_origin == origin


def safe_next(value: str | None) -> str:
    """Only local absolute paths: never another site, never protocol-relative."""
    if not value or not value.startswith("/") or value.startswith("//") or "\\" in value:
        return "/"
    return value
