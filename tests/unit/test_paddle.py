"""Paddle's signed notifications add and take back credit (ADR 0026)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from previewit.adapters.ai.keys import KeysFileError, load_house_keys
from previewit.adapters.payments.paddle import PaddleNotifications, sign, signature_ok
from tests.unit.test_credits import ADA, World

SECRET = "pdl_ntfset_01test_secret"
NOW = 1_795_000_000


def completed(transaction: str = "txn_01", user: str = ADA, price: str = "pri_10") -> bytes:
    return json.dumps({
        "event_id": "evt_01", "event_type": "transaction.completed",
        "data": {
            "id": transaction, "status": "completed", "currency_code": "EUR",
            "custom_data": {"user_id": user},
            "items": [{"price": {"id": price}, "quantity": 1}],
            "details": {"totals": {"grand_total": "1000"}},
        },
    }).encode()  # fmt: skip


def refund(status: str = "approved", total: str = "1000", event: str = "adjustment.updated"):
    return json.dumps({
        "event_id": "evt_02", "event_type": event,
        "data": {"id": "adj_01", "action": "refund", "status": status,
                 "transaction_id": "txn_01", "totals": {"total": total}},
    }).encode()  # fmt: skip


@pytest.fixture
def w() -> World:
    return World()


def paddle(w: World) -> PaddleNotifications:
    return PaddleNotifications(w.credits, SECRET, clock=lambda: NOW)


def test_the_signature_is_checked_against_the_raw_body() -> None:
    body = b'{"a":1}'
    header = sign(body, SECRET, NOW)
    assert signature_ok(header, body, SECRET, NOW)
    assert signature_ok(header + ";h1=" + "0" * 64, body, SECRET, NOW)  # a second secret, rotating
    assert not signature_ok(header, b'{"a": 1}', SECRET, NOW)  # one space changes everything
    assert not signature_ok(header, body, "other", NOW)
    assert not signature_ok(header, body, SECRET, NOW + 301)  # too old: a replay
    assert not signature_ok("h1=abc", body, SECRET, NOW)
    assert not signature_ok("", body, SECRET, NOW)
    assert not signature_ok(header, body, "", NOW)


def test_a_completed_transaction_adds_credit_once(w: World) -> None:
    body = completed()
    assert paddle(w).handle(sign(body, SECRET, NOW), body) == 200
    assert paddle(w).handle(sign(body, SECRET, NOW), body) == 200  # Paddle retries
    assert w.credits.balance(ADA) == 1000


def test_an_unsigned_or_unreadable_notification_changes_nothing(w: World) -> None:
    body = completed()
    assert paddle(w).handle(sign(body, "guess", NOW), body) == 401
    assert paddle(w).handle(sign(b"not json", SECRET, NOW), b"not json") == 400
    stranger = completed(user="nobody")
    assert paddle(w).handle(sign(stranger, SECRET, NOW), stranger) == 200  # logged, not retried
    assert w.credits.balance(ADA) == 0


def test_an_approved_refund_takes_the_credit_back(w: World) -> None:
    body = completed()
    paddle(w).handle(sign(body, SECRET, NOW), body)
    pending = refund(status="pending_approval", event="adjustment.created")
    paddle(w).handle(sign(pending, SECRET, NOW), pending)
    assert w.credits.balance(ADA) == 1000  # not yet
    approved = refund(total="500")
    assert paddle(w).handle(sign(approved, SECRET, NOW), approved) == 200
    assert w.credits.balance(ADA) == 500


def test_other_events_are_acknowledged_and_ignored(w: World) -> None:
    body = json.dumps({"event_type": "customer.created", "data": {"id": "ctm_1"}}).encode()
    assert paddle(w).handle(sign(body, SECRET, NOW), body) == 200


def test_previewits_own_keys_come_from_a_private_file(tmp_path: Path) -> None:
    file = tmp_path / "ai-keys.toml"
    file.write_text('anthropic = " sk-ant-house "\n')
    os.chmod(file, 0o600)
    assert load_house_keys(str(file), {"anthropic", "openai"}) == {"anthropic": "sk-ant-house"}
    assert load_house_keys(None, {"anthropic"}) == {}
    file.write_text('nobody = "x"\n')
    with pytest.raises(KeysFileError, match="no model service"):
        load_house_keys(str(file), {"anthropic"})
