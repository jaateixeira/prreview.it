"""Credit kept in memory, for tests (ADR 0026)."""

from __future__ import annotations

from previewit.domain.credits import CreditEntry, CreditKind
from previewit.domain.identity import UserId


class InMemoryCreditRepository:
    def __init__(self) -> None:
        self._rows: list[CreditEntry] = []

    def add(self, entry: CreditEntry) -> bool:
        if self.find(entry.kind, entry.reference) is not None:
            return False
        self._rows.append(entry)
        return True

    def find(self, kind: CreditKind, reference: str) -> CreditEntry | None:
        return next((e for e in self._rows if e.kind is kind and e.reference == reference), None)

    def related(self, kind: CreditKind, related: str) -> list[CreditEntry]:
        return [e for e in self._rows if e.kind is kind and e.related == related]

    def balance(self, user_id: UserId) -> int:
        return sum(e.amount_cents for e in self._rows if e.user_id == user_id)

    def entries(self, user_id: UserId, limit: int = 100) -> list[CreditEntry]:
        mine = [e for e in self._rows if e.user_id == user_id]
        return list(reversed(mine))[:limit]
