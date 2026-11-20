"""Prepared review requests in the database (ADR 0023)."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy import Engine, delete, func, insert, select

from previewit.adapters.persistence.tables import prepared_requests
from previewit.application.prepared_requests import ASSISTANT, PreparedRequest


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value  # SQLite drops the zone


class SqlPreparedRequestRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def add(self, token_hash: str, prepared: PreparedRequest) -> None:
        payload = {
            "title": prepared.title,
            "web_address": prepared.web_address,
            "text": prepared.text,
            "reviewers": list(prepared.reviewers),
            "message": prepared.message,
            "due": prepared.due,
            "source": prepared.source,
            "due_time": prepared.due_time,
            "ai_models": list(prepared.ai_models),
        }
        with self._engine.begin() as conn:
            conn.execute(
                insert(prepared_requests).values(
                    token_hash=token_hash,
                    payload=json.dumps(payload, ensure_ascii=False),
                    created_at=prepared.created_at,
                    expires_at=prepared.expires_at,
                    file_name=prepared.file_name or None,
                    file_content=prepared.file_content,
                )
            )

    def get(self, token_hash: str) -> PreparedRequest | None:
        with self._engine.connect() as conn:
            row = conn.execute(
                select(prepared_requests).where(prepared_requests.c.token_hash == token_hash)
            ).one_or_none()
        if row is None:
            return None
        data = json.loads(row.payload)
        content = bytes(row.file_content) if row.file_content is not None else None
        return PreparedRequest(
            data["title"], data["web_address"], data["text"], tuple(data["reviewers"]),
            data["message"], data["due"], _utc(row.created_at), _utc(row.expires_at),
            data.get("source", ASSISTANT), row.file_name or "", content, data.get("due_time", ""),
            tuple(data.get("ai_models", ())),
        )  # fmt: skip

    def delete(self, token_hash: str) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                delete(prepared_requests).where(prepared_requests.c.token_hash == token_hash)
            )

    def delete_expired(self, now: datetime) -> None:
        with self._engine.begin() as conn:
            conn.execute(delete(prepared_requests).where(prepared_requests.c.expires_at <= now))

    def count(self) -> int:
        with self._engine.connect() as conn:
            return conn.execute(select(func.count()).select_from(prepared_requests)).scalar_one()

    def count_files(self) -> int:
        query = select(func.count()).where(prepared_requests.c.file_content.is_not(None))
        with self._engine.connect() as conn:
            return conn.execute(query).scalar_one()
