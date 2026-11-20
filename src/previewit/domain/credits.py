"""Credit (ADR 0026): euros a person bought through Paddle, spent on AI reviews when they give
no key of their own.

Money is whole euro cents. Credit belongs to the person, like their account, not to an
organization. Every change is an entry and the balance is their sum, so the history explains
every cent.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_CEILING, Decimal
from enum import StrEnum
from typing import NewType

from previewit.domain.identity import UserId

CreditEntryId = NewType("CreditEntryId", str)


class InvalidCreditPack(ValueError):
    """A credit pack in the configuration that cannot be right."""


class CreditKind(StrEnum):
    PURCHASE = "purchase"  # bought through Paddle: reference is the transaction (txn_...)
    REFUND = "refund"  # Paddle refunded a purchase: reference is the adjustment (adj_...)
    HOLD = "hold"  # set aside for an AI review being written: reference is the AI review
    RELEASE = "release"  # what was held and not spent comes back: reference is the AI review


@dataclass(frozen=True)
class CreditEntry:
    id: CreditEntryId
    user_id: UserId
    amount_cents: int  # positive adds credit, negative takes it
    kind: CreditKind
    reference: str  # unique for its kind, so nothing is counted twice
    created_at: datetime
    paid_cents: int = 0  # for a purchase: what the buyer paid, tax included
    related: str = ""  # for a refund: the purchase's transaction


@dataclass(frozen=True)
class CreditPack:
    """One thing to buy: `whole_euros` of credit for that price, tax included."""

    price_id: str  # Paddle's price (pri_...)
    whole_euros: int

    def __post_init__(self) -> None:
        if not self.price_id.strip():
            raise InvalidCreditPack("a credit pack needs Paddle's price id")
        if not 1 <= self.whole_euros <= 1_000:
            raise InvalidCreditPack(f"{self.price_id}: a pack is 1 to 1,000 euros")

    @property
    def cents(self) -> int:
        return self.whole_euros * 100


@dataclass(frozen=True)
class CreditPricing:
    """How a model service's price in US dollars becomes a price in credit."""

    usd_to_eur: Decimal  # euros for one dollar; err high
    margin: Decimal  # on top of the cost, e.g. 0.30
    fees_and_tax: Decimal  # on top again: VAT in the buyer's country and Paddle's fee

    def cents(self, cost_usd: Decimal) -> int:
        """The credit an AI review costing `cost_usd` takes, rounded up to a whole cent."""
        if cost_usd <= 0:
            return 0
        eur = cost_usd * self.usd_to_eur * (1 + self.margin) * (1 + self.fees_and_tax)
        return max(int((eur * 100).to_integral_value(ROUND_CEILING)), 1)


def balance(entries: list[CreditEntry]) -> int:
    return sum(entry.amount_cents for entry in entries)


def euros(cents: int) -> str:
    """Euros for people: "€12.50"; a debt is "-€3.00"."""
    sign = "-" if cents < 0 else ""
    whole, part = divmod(abs(cents), 100)
    return f"{sign}€{whole}.{part:02d}"
