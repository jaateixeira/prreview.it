"""Credit (ADR 0026): what a person bought through Paddle and what their AI reviews spent.

Paddle tells Previewit about purchases and refunds; the payment adapter calls
`record_purchase` and `record_refund`, each safe to repeat. An AI review paid with credit holds
the most it may cost, then gives back what it did not spend.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import datetime
from typing import Protocol

from previewit.application.ports import UserRepository
from previewit.domain.credits import CreditEntry, CreditEntryId, CreditKind, CreditPack
from previewit.domain.identity import UserId


class NotEnoughCredit(Exception):
    def __init__(self, balance: int, needed: int) -> None:
        super().__init__(f"balance {balance} cents, needed {needed}")
        self.balance = balance
        self.needed = needed


class UnknownBuyer(Exception):
    """A purchase names nobody Previewit knows: it is not credited to anyone."""


class CreditRepository(Protocol):
    def add(self, entry: CreditEntry) -> bool:
        """Store it. False, and nothing stored, if its kind and reference are already there."""
        ...

    def find(self, kind: CreditKind, reference: str) -> CreditEntry | None: ...

    def related(self, kind: CreditKind, related: str) -> list[CreditEntry]: ...

    def balance(self, user_id: UserId) -> int: ...

    def entries(self, user_id: UserId, limit: int = 100) -> list[CreditEntry]:
        """Newest first."""
        ...


class CreditsService:
    def __init__(
        self,
        repo: CreditRepository,
        users: UserRepository,
        packs: Sequence[CreditPack],
        *,
        ids: Callable[[], str],
        now: Callable[[], datetime],
    ) -> None:
        self._repo = repo
        self._users = users
        self.packs = tuple(packs)
        self._by_price = {pack.price_id: pack for pack in packs}
        self._ids = ids
        self._now = now
        self._lock = threading.Lock()  # one hold at a time, so two cannot spend the same cent

    def balance(self, user_id: UserId) -> int:
        return self._repo.balance(user_id)

    def history(self, user_id: UserId) -> list[CreditEntry]:
        return self._repo.entries(user_id)

    # -- from Paddle ---------------------------------------------------------------------------

    def record_purchase(
        self,
        transaction_id: str,
        user_id: UserId,
        items: Sequence[tuple[str, int]],
        *,
        paid_cents: int,
    ) -> bool:
        """Add the credit of the packs bought in one completed transaction. True if added now;
        False if it was already added or bought nothing Previewit sells."""
        if self._users.get(user_id) is None:
            raise UnknownBuyer(user_id)
        cents = sum(
            self._by_price[price].cents * max(quantity, 0)
            for price, quantity in items
            if price in self._by_price
        )
        if cents <= 0:
            return False
        entry = self._entry(user_id, cents, CreditKind.PURCHASE, transaction_id)
        return self._repo.add(replace(entry, paid_cents=max(paid_cents, 0)))

    def record_refund(
        self, adjustment_id: str, transaction_id: str, *, refunded_cents: int
    ) -> bool:
        """Take back the share of a purchase that Paddle refunded, never more than it added.
        True if taken now; False if already taken or the purchase is unknown."""
        purchase = self._repo.find(CreditKind.PURCHASE, transaction_id)
        if purchase is None or refunded_cents <= 0:
            return False
        paid = purchase.paid_cents or purchase.amount_cents
        share = -(-purchase.amount_cents * refunded_cents // paid)  # rounded up
        taken = -sum(e.amount_cents for e in self._repo.related(CreditKind.REFUND, transaction_id))
        cents = min(share, purchase.amount_cents - taken)
        if cents <= 0:
            return False
        entry = self._entry(purchase.user_id, -cents, CreditKind.REFUND, adjustment_id)
        return self._repo.add(replace(entry, related=transaction_id))

    # -- AI reviews ------------------------------------------------------------------------------

    def hold(self, user_id: UserId, review_id: str, cents: int) -> None:
        """Set aside the most an AI review may cost. Raises NotEnoughCredit."""
        with self._lock:
            have = self._repo.balance(user_id)
            if have < cents:
                raise NotEnoughCredit(have, cents)
            self._repo.add(self._entry(user_id, -cents, CreditKind.HOLD, review_id))

    def settle(self, user_id: UserId, review_id: str, spent_cents: int) -> None:
        """The review is written: keep what it cost (at most what was held), give back the rest."""
        held = self._repo.find(CreditKind.HOLD, review_id)
        if held is None:
            return
        back = -held.amount_cents - min(max(spent_cents, 0), -held.amount_cents)
        self._repo.add(self._entry(user_id, back, CreditKind.RELEASE, review_id))

    def release(self, user_id: UserId, review_id: str) -> None:
        """The review failed: give everything back."""
        self.settle(user_id, review_id, 0)

    def _entry(self, user_id: UserId, cents: int, kind: CreditKind, reference: str) -> CreditEntry:
        return CreditEntry(CreditEntryId(self._ids()), user_id, cents, kind, reference, self._now())
