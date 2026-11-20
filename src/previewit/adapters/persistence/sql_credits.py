"""Credit in the database (ADR 0026). A unique (kind, reference) makes every purchase, refund,
hold and release count once, however often Paddle repeats a notification."""

from __future__ import annotations

from datetime import UTC
from typing import Any

from sqlalchemy import Engine, func, insert, select
from sqlalchemy.exc import IntegrityError

from previewit.adapters.persistence.tables import credit_entries
from previewit.domain.credits import CreditEntry, CreditEntryId, CreditKind
from previewit.domain.identity import UserId


def _entry(row: Any) -> CreditEntry:
    created = row.created_at
    return CreditEntry(
        id=CreditEntryId(row.id),
        user_id=UserId(row.user_id),
        amount_cents=row.amount_cents,
        kind=CreditKind(row.kind),
        reference=row.reference,
        created_at=created.replace(tzinfo=UTC) if created.tzinfo is None else created,
        paid_cents=row.paid_cents,
        related=row.related,
    )


class SqlCreditRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def add(self, entry: CreditEntry) -> bool:
        try:
            with self._engine.begin() as conn:
                conn.execute(
                    insert(credit_entries).values(
                        id=entry.id,
                        user_id=entry.user_id,
                        amount_cents=entry.amount_cents,
                        kind=entry.kind.value,
                        reference=entry.reference,
                        related=entry.related,
                        paid_cents=entry.paid_cents,
                        created_at=entry.created_at,
                    )
                )
        except IntegrityError:
            return False  # already counted
        return True

    def find(self, kind: CreditKind, reference: str) -> CreditEntry | None:
        query = select(credit_entries).where(
            credit_entries.c.kind == kind.value, credit_entries.c.reference == reference
        )
        with self._engine.connect() as conn:
            row = conn.execute(query).one_or_none()
        return _entry(row) if row is not None else None

    def related(self, kind: CreditKind, related: str) -> list[CreditEntry]:
        query = select(credit_entries).where(
            credit_entries.c.kind == kind.value, credit_entries.c.related == related
        )
        with self._engine.connect() as conn:
            return [_entry(row) for row in conn.execute(query)]

    def balance(self, user_id: UserId) -> int:
        query = select(func.coalesce(func.sum(credit_entries.c.amount_cents), 0)).where(
            credit_entries.c.user_id == user_id
        )
        with self._engine.connect() as conn:
            return int(conn.execute(query).scalar_one())

    def entries(self, user_id: UserId, limit: int = 100) -> list[CreditEntry]:
        query = (
            select(credit_entries)
            .where(credit_entries.c.user_id == user_id)
            .order_by(credit_entries.c.seq.desc())
            .limit(limit)
        )
        with self._engine.connect() as conn:
            return [_entry(row) for row in conn.execute(query)]
