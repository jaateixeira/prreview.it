"""Pricing, the legal pages Paddle's domain review reads, the Credit page and Paddle's signed
notifications, through the web layer (ADR 0026)."""

from __future__ import annotations

import json
import time

import pytest

from previewit.adapters.payments.paddle import sign
from previewit.domain.identity import Email
from tests.integration.test_ai_reviews_web import KEY, send, submission_of, words
from tests.integration.test_quick_review_web import organizer
from tests.integration.web_fakes import PADDLE_SECRET, Harness, make_harness
from tests.unit.test_ai_reviews_service import HOUSE, SONNET

PUBLIC = ["/pricing", "/terms", "/refunds", "/privacy", "/contact"]
MOR = "Paddle.com is the Merchant of Record for all our orders."


def notify(h: Harness, event: dict, secret: str = PADDLE_SECRET):
    body = json.dumps(event).encode()
    header = sign(body, secret, int(time.time()))
    return h.client.post("/paddle/webhook", content=body, headers={"Paddle-Signature": header})


def bought(user_id: str, transaction: str = "txn_01", price: str = "pri_10") -> dict:
    return {
        "event_type": "transaction.completed",
        "data": {
            "id": transaction, "custom_data": {"user_id": user_id},
            "items": [{"price": {"id": price}, "quantity": 1}],
            "details": {"totals": {"grand_total": "1000"}},
        },
    }  # fmt: skip


def user_id_of(h: Harness, email: str) -> str:
    user = h.auth._users.find_by_email(Email(email))  # type: ignore[attr-defined]
    assert user is not None
    return user.id


# -- what Paddle's domain review reads ------------------------------------------------------------


@pytest.mark.parametrize("path", PUBLIC)
def test_every_page_paddle_reviews_is_public_and_linked_from_every_page(path: str) -> None:
    visitor = make_harness().new_client()
    page = visitor.get(path)
    assert page.status_code == 200, path
    for link in PUBLIC:
        assert f'href="{link}"' in page.text  # the footer, everywhere
    assert f'href="{path}"' in visitor.get("/").text


def test_the_terms_name_the_seller_paddle_and_the_ai_rules() -> None:
    terms = words(make_harness().new_client().get("/terms").text)
    assert "run by Sam Seller, trading as Previewit" in terms
    assert "Testikatu 1, 40100 Jyväskylä, Finland" in terms and "+358 40 123 4567" in terms
    assert "Our order process is conducted by our online reseller Paddle.com." in terms
    assert MOR in terms and "handles returns" in terms
    for rule in ("deepfakes", "jailbreaking", "doxxing", "not professional advice", "infringe"):
        assert rule in terms
    assert "Finnish law" in terms and "has not filled in" not in terms


def test_the_refund_policy_is_thirty_days_for_any_reason() -> None:
    refunds = words(make_harness().new_client().get("/refunds").text)
    assert "full refund of any purchase within 30 days of buying it, for any reason" in refunds
    assert "paddle.net" in refunds and MOR in refunds
    for qualifier in ("unused", "final", "no refunds"):
        assert qualifier not in refunds.lower()


def test_the_privacy_notice_has_what_the_gdpr_asks_for() -> None:
    privacy = words(make_harness().new_client().get("/privacy").text)
    assert "controller of your personal data is Sam Seller" in privacy
    assert "Mail Co SAS, France: sends our emails" in privacy  # from the settings
    for part in (
        "Legal basis", "Contract (art. 6(1)(b))", "standard contractual clauses",
        "How long we keep it", "within one month", "Data Protection Ombudsman",
        "pv_session", "pv_csrf", "never stored",
    ):  # fmt: skip
        assert part in privacy, part


def test_pricing_shows_the_packs_and_what_an_ai_review_costs() -> None:
    pricing = words(make_harness().new_client().get("/pricing").text)
    assert "<strong>€5</strong> of credit for €5" in pricing
    assert "<strong>€10</strong> of credit for €10" in pricing
    assert "Prices include VAT where it applies" in pricing
    assert "What one AI review costs" in pricing and "Anthropic/Sonnet" in pricing
    assert MOR in pricing and 'data-token="test_client_token"' in pricing


def test_without_seller_details_the_pages_say_so() -> None:
    from previewit.adapters.web.money_routes import Seller

    assert not Seller("", "Previewit", "", "", "", "", "", ()).complete


# -- credit ----------------------------------------------------------------------------------------


def test_the_credit_page_opens_paddle_for_the_signed_in_buyer() -> None:
    h, client = organizer()
    assert h.new_client().get("/credit").headers["location"] == "/login?next=%2Fcredit"
    page = client.get("/credit")
    assert page.status_code == 200 and "You have <strong>€0.00</strong>" in page.text
    me = user_id_of(h, "olga@x.fi")
    assert f'data-user="{me}"' in page.text and 'data-email="olga@x.fi"' in page.text
    assert 'data-price="pri_5"' in page.text and 'data-price="pri_10"' in page.text
    assert "js/credit.js" in page.text
    assert 'href="/credit"' in client.get("/account").text


def test_a_signed_notification_adds_credit_and_a_refund_takes_it_back() -> None:
    h, client = organizer()
    me = user_id_of(h, "olga@x.fi")
    assert notify(h, bought(me)).status_code == 200
    assert notify(h, bought(me)).status_code == 200  # Paddle retries: counted once
    assert "You have <strong>€10.00</strong>" in client.get("/credit").text
    refund = {
        "event_type": "adjustment.updated",
        "data": {"id": "adj_01", "action": "refund", "status": "approved",
                 "transaction_id": "txn_01", "totals": {"total": "1000"}},
    }  # fmt: skip
    assert notify(h, refund).status_code == 200
    page = client.get("/credit").text
    assert "You have <strong>€0.00</strong>" in page and "Refunded (txn_01)" in page


def test_an_unsigned_notification_is_refused() -> None:
    h, _ = organizer()
    me = user_id_of(h, "olga@x.fi")
    assert notify(h, bought(me), secret="guessed").status_code == 401
    assert h.client.post("/paddle/webhook", content=b"{}").status_code == 401
    assert h.credits.balance(me) == 0  # type: ignore[arg-type]


def test_credit_pays_for_an_ai_review_without_a_key() -> None:
    h, client = organizer()
    me = user_id_of(h, "olga@x.fi")
    notify(h, bought(me))
    done = send(client, {"ai_model": [SONNET.key]})
    assert done.status_code == 200 and "is reading your work" in words(done.text)
    assert h.ai_writer.calls[-1][:2] == (SONNET.key, HOUSE)
    section = client.get(f"/submissions/{submission_of(done)}/ai").text
    assert "A clear essay." in section and "from your credit" in words(section)
    assert h.credits.balance(me) < 1000  # type: ignore[arg-type]
    assert KEY not in section and HOUSE not in section
