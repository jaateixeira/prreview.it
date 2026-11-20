"""Credit (ADR 0026): euros bought through Paddle in packs, spent on AI reviews when the person
gives no key of their own. Every change is an entry; the balance is their sum."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from itertools import count

import pytest
from hypothesis import given
from hypothesis import strategies as st

from previewit.adapters.persistence.memory import InMemoryUserRepository
from previewit.adapters.persistence.memory_credits import InMemoryCreditRepository
from previewit.application.credits import CreditsService, NotEnoughCredit, UnknownBuyer
from previewit.domain.credits import (
    CreditKind,
    CreditPack,
    CreditPricing,
    InvalidCreditPack,
    euros,
)
from previewit.domain.identity import Email, User, UserId

ADA = UserId("ada")
NOW = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
PACKS = (CreditPack("pri_5", 5), CreditPack("pri_10", 10), CreditPack("pri_25", 25))
PRICING = CreditPricing(
    usd_to_eur=Decimal("0.9"), margin=Decimal("0.3"), fees_and_tax=Decimal("0.4")
)


ADA_USER = User(ADA, "Ada", Email("ada@x.fi"), True, frozenset(), False)


class World:
    def __init__(self, repo=None) -> None:
        self.now = NOW
        self.repo = repo if repo is not None else InMemoryCreditRepository()
        ids = count(1)
        users = InMemoryUserRepository()
        users.add_user(ADA_USER, None)
        self.credits = CreditsService(
            self.repo, users, PACKS, ids=lambda: f"c{next(ids)}", now=lambda: self.now
        )


@pytest.fixture
def w() -> World:
    return World()


# -- money -----------------------------------------------------------------------------------------


def test_euros_are_written_for_people() -> None:
    assert euros(0) == "€0.00" and euros(5) == "€0.05" and euros(1250) == "€12.50"
    assert euros(-300) == "-€3.00"


def test_a_price_in_credit_covers_the_service_the_tax_the_fees_and_a_margin() -> None:
    # $1.00 → €0.90, +30% margin → €1.17, +40% for VAT and Paddle's fee → €1.638 → €1.64
    assert PRICING.cents(Decimal("1.00")) == 164
    assert PRICING.cents(Decimal(0)) == 0
    assert PRICING.cents(Decimal("0.0001")) == 1  # never free when it costs something


@given(st.decimals(0, 100, places=6), st.decimals(0, 100, places=6))
def test_more_cost_never_costs_less_credit(a: Decimal, b: Decimal) -> None:
    low, high = sorted((a, b))
    assert 0 <= PRICING.cents(low) <= PRICING.cents(high)
    assert PRICING.cents(low) >= low * Decimal("0.9") * 100  # never below cost


def test_a_pack_is_a_whole_number_of_euros() -> None:
    with pytest.raises(InvalidCreditPack):
        CreditPack("pri_x", 0)
    with pytest.raises(InvalidCreditPack):
        CreditPack("", 5)
    assert CreditPack("pri_x", 10).cents == 1000


# -- buying ----------------------------------------------------------------------------------------


def test_a_completed_purchase_adds_the_packs_once(w: World) -> None:
    assert w.credits.record_purchase("txn_1", ADA, [("pri_10", 1), ("pri_5", 2)], paid_cents=2000)
    assert w.credits.balance(ADA) == 2000
    assert not w.credits.record_purchase("txn_1", ADA, [("pri_10", 1)], paid_cents=1000)  # again
    assert w.credits.balance(ADA) == 2000
    [entry] = w.credits.history(ADA)
    assert entry.kind is CreditKind.PURCHASE and entry.reference == "txn_1"


def test_unknown_prices_add_nothing_and_unknown_buyers_are_refused(w: World) -> None:
    assert not w.credits.record_purchase("txn_2", ADA, [("pri_other", 1)], paid_cents=500)
    assert w.credits.balance(ADA) == 0
    with pytest.raises(UnknownBuyer):
        w.credits.record_purchase("txn_3", UserId("nobody"), [("pri_5", 1)], paid_cents=500)


def test_a_refund_takes_back_the_refunded_share_once(w: World) -> None:
    w.credits.record_purchase("txn_1", ADA, [("pri_10", 1)], paid_cents=1000)
    assert w.credits.record_refund("adj_1", "txn_1", refunded_cents=500)  # half
    assert w.credits.balance(ADA) == 500
    assert not w.credits.record_refund("adj_1", "txn_1", refunded_cents=500)
    assert w.credits.record_refund("adj_2", "txn_1", refunded_cents=900)  # never more than bought
    assert w.credits.balance(ADA) == 0
    assert not w.credits.record_refund("adj_3", "txn_unknown", refunded_cents=500)


def test_credit_spent_and_then_refunded_leaves_a_debt(w: World) -> None:
    w.credits.record_purchase("txn_1", ADA, [("pri_5", 1)], paid_cents=500)
    w.credits.hold(ADA, "ai1", 300)
    w.credits.settle(ADA, "ai1", 300)
    w.credits.record_refund("adj_1", "txn_1", refunded_cents=500)
    assert w.credits.balance(ADA) == -300


# -- spending --------------------------------------------------------------------------------------


def test_an_ai_review_holds_the_most_it_may_cost_then_pays_what_it_cost(w: World) -> None:
    w.credits.record_purchase("txn_1", ADA, [("pri_5", 1)], paid_cents=500)
    w.credits.hold(ADA, "ai1", 120)
    assert w.credits.balance(ADA) == 380
    w.credits.settle(ADA, "ai1", 45)
    assert w.credits.balance(ADA) == 455
    w.credits.settle(ADA, "ai1", 45)  # once only
    assert w.credits.balance(ADA) == 455
    assert [e.kind for e in w.credits.history(ADA)] == [
        CreditKind.RELEASE,
        CreditKind.HOLD,
        CreditKind.PURCHASE,
    ]  # newest first


def test_a_failed_review_gives_everything_back(w: World) -> None:
    w.credits.record_purchase("txn_1", ADA, [("pri_5", 1)], paid_cents=500)
    w.credits.hold(ADA, "ai1", 120)
    w.credits.release(ADA, "ai1")
    assert w.credits.balance(ADA) == 500


def test_a_settlement_never_charges_more_than_was_held(w: World) -> None:
    w.credits.record_purchase("txn_1", ADA, [("pri_5", 1)], paid_cents=500)
    w.credits.hold(ADA, "ai1", 100)
    w.credits.settle(ADA, "ai1", 400)
    assert w.credits.balance(ADA) == 400


def test_not_enough_credit_holds_nothing(w: World) -> None:
    w.credits.record_purchase("txn_1", ADA, [("pri_5", 1)], paid_cents=500)
    with pytest.raises(NotEnoughCredit) as refused:
        w.credits.hold(ADA, "ai1", 501)
    assert (refused.value.balance, refused.value.needed) == (500, 501)
    assert w.credits.balance(ADA) == 500
    w.now += timedelta(seconds=1)
    w.credits.hold(ADA, "ai2", 500)  # exactly enough
    assert w.credits.balance(ADA) == 0
