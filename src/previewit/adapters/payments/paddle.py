"""Paddle's notifications (ADR 0026): a completed transaction adds credit, an approved refund
takes it back.

Paddle signs each notification: the `Paddle-Signature` header is `ts=<unix time>;h1=<hex>`,
where h1 is HMAC-SHA256 of `<ts>:<raw body>` keyed with the notification destination's
secret. Previewit checks it against the raw bytes, refuses notifications older than five
minutes, and logs only ids, never the buyer's details. Each notification is safe to repeat.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from collections.abc import Callable
from typing import Any

from loguru import logger

from previewit.application.credits import CreditsService, UnknownBuyer
from previewit.domain.identity import UserId

TOLERANCE_SECONDS = 300
REFUND_EVENTS = {"adjustment.created", "adjustment.updated"}


def signature_ok(header: str, body: bytes, secret: str, now: float) -> bool:
    """True if `header` signs `body` with `secret`, sent within the last five minutes."""
    parts = [part.strip().partition("=") for part in header.split(";")]
    stamps = [value for name, _, value in parts if name == "ts"]
    signatures = [value for name, _, value in parts if name == "h1"]
    if len(stamps) != 1 or not stamps[0].isdigit() or not signatures or not secret:
        return False
    if abs(now - int(stamps[0])) > TOLERANCE_SECONDS:
        return False
    signed = stamps[0].encode() + b":" + body
    expected = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(expected, given.lower()) for given in signatures)


def sign(body: bytes, secret: str, at: int) -> str:
    """The header Paddle would send: for tests and the acceptance scenarios."""
    digest = hmac.new(secret.encode(), str(at).encode() + b":" + body, hashlib.sha256)
    return f"ts={at};h1={digest.hexdigest()}"


class PaddleNotifications:
    def __init__(
        self, credits: CreditsService, secret: str, clock: Callable[[], float] = time.time
    ) -> None:
        self._credits = credits
        self._secret = secret
        self._clock = clock

    def handle(self, header: str, body: bytes) -> int:
        """The status to answer Paddle with: 200 when handled or not of interest, 401 when the
        signature is wrong (Paddle retries; an attacker learns nothing), 400 when unreadable."""
        if not signature_ok(header, body, self._secret, self._clock()):
            logger.warning("Paddle notification refused: bad or old signature")
            return 401
        try:
            event = json.loads(body)
            kind = str(event["event_type"])
            data = event["data"]
        except (ValueError, KeyError, TypeError):
            return 400
        if not isinstance(data, dict):
            return 400
        if kind == "transaction.completed":
            self._purchase(data)
        elif kind in REFUND_EVENTS:
            self._refund(data)
        return 200

    def _purchase(self, data: dict[str, Any]) -> None:
        transaction = str(data.get("id", ""))
        custom = data.get("custom_data") or {}
        user = str(custom.get("user_id", "")) if isinstance(custom, dict) else ""
        items = [
            (str((item.get("price") or {}).get("id", "")), int(item.get("quantity") or 0))
            for item in data.get("items") or []
            if isinstance(item, dict)
        ]
        totals = (data.get("details") or {}).get("totals") or {}
        paid = _cents(totals.get("grand_total") if isinstance(totals, dict) else None)
        if not transaction or not user:
            logger.warning("Paddle transaction {} names no Previewit user", transaction or "?")
            return
        try:
            added = self._credits.record_purchase(transaction, UserId(user), items, paid_cents=paid)
        except UnknownBuyer:
            logger.warning("Paddle transaction {} names an unknown user", transaction)
            return
        logger.info("Paddle transaction {}: credit {}", transaction, "added" if added else "known")

    def _refund(self, data: dict[str, Any]) -> None:
        if data.get("action") != "refund" or data.get("status") != "approved":
            return  # pending refunds wait; credits and chargebacks are not refunds
        adjustment = str(data.get("id", ""))
        transaction = str(data.get("transaction_id", ""))
        refunded = _cents((data.get("totals") or {}).get("total"))
        taken = self._credits.record_refund(adjustment, transaction, refunded_cents=refunded)
        logger.info("Paddle refund {}: credit {}", adjustment, "taken back" if taken else "known")


def _cents(value: object) -> int:
    """Paddle sends amounts as strings of the smallest unit: "1000" is €10.00."""
    try:
        return int(str(value))
    except ValueError:
        return 0
