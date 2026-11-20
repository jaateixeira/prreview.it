"""Prepared review requests (ADR 0023, ADR 0024).

A Request a review form, filled in and kept under a secret link, waiting for a person to sign
in, check it and send it. Nothing is sent before that. Two kinds:

- an AI assistant prepares one through the MCP service (a web page's address or some text, the
  reviewers, a message, a due date) and it waits a week;
- a visitor fills in the form before signing in and presses Send it out: the form, with its
  file, waits one hour while they sign in or create an account, then it is deleted.

Nobody needs an account to make one, so the rules are strict about size and the store is bounded.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from hashlib import sha256
from typing import Protocol

from previewit.application.web_pages import PageUnreachable, normalise_address
from previewit.domain.email_list import MAX_EMAILS, parse_typed

PREPARED_DAYS = 7
VISITOR_HOURS = 1  # a form kept while its owner signs in, file included
MAX_TEXT_BYTES = 100_000  # from an AI assistant
MAX_VISITOR_TEXT_BYTES = 400_000  # the most text the form itself takes
MAX_FILE_BYTES = 10_000_000  # the largest file Request a review takes
MAX_FILES_WAITING = 200  # files kept for visitors, site-wide: 2 GB at the very most
MAX_TITLE = 200
MAX_MESSAGE = 2000
MAX_PENDING = 10_000  # waiting prepared requests, site-wide
MAX_AI_MODELS = 3  # AI models a visitor may have chosen (ADR 0025)

_TIME = re.compile(r"[0-2]\d:[0-5]\d")

ASSISTANT = "assistant"
VISITOR = "visitor"


class InvalidPreparedRequest(ValueError):
    """The request cannot be prepared. The message is for the AI assistant to fix it."""


@dataclass(frozen=True)
class PreparedRequest:
    title: str
    web_address: str  # tidied; "" when the work is text
    text: str  # "" when the work is a web page
    reviewers: tuple[str, ...]  # email addresses, each once
    message: str  # a few words for the reviewers
    due: str  # "YYYY-MM-DD", or "" for the usual two weeks
    created_at: datetime
    expires_at: datetime
    source: str = ASSISTANT  # ASSISTANT or VISITOR
    file_name: str = ""
    file_content: bytes | None = None  # a visitor's file, kept for an hour
    due_time: str = ""  # "HH:MM" when a visitor chose another time than 16:00
    ai_models: tuple[str, ...] = ()  # AI models a visitor chose (ADR 0025); keys are never kept


class PreparedRequestRepository(Protocol):
    def add(self, token_hash: str, prepared: PreparedRequest) -> None: ...
    def get(self, token_hash: str) -> PreparedRequest | None: ...
    def delete(self, token_hash: str) -> None: ...
    def delete_expired(self, now: datetime) -> None: ...
    def count(self) -> int: ...
    def count_files(self) -> int: ...


def token_hash(token: str) -> str:
    return sha256(token.encode("utf-8")).hexdigest()


class PreparedRequestsService:
    def __init__(
        self,
        repo: PreparedRequestRepository,
        new_token: Callable[[], str],
        now: Callable[[], datetime],
    ) -> None:
        self._repo = repo
        self._new_token = new_token
        self._now = now

    def prepare(
        self,
        *,
        title: str = "",
        web_address: str = "",
        text: str = "",
        reviewers: Sequence[str] = (),
        message: str = "",
        due: str = "",
    ) -> tuple[str, PreparedRequest]:
        """Keep an AI assistant's request for the person to check. Returns the secret token."""
        now = self._now()
        title = _title(title)
        address, text = web_address.strip(), text.strip()
        either = "Give either web_address (a public web page) or text (the work itself)"
        if address and text:
            raise InvalidPreparedRequest(either + ", not both.")
        if not address and not text:
            raise InvalidPreparedRequest(either + ".")
        if address:
            try:
                address = normalise_address(address)
            except PageUnreachable as problem:
                raise InvalidPreparedRequest(str(problem)) from None
        if len(text.encode("utf-8")) > MAX_TEXT_BYTES:
            raise InvalidPreparedRequest(
                "The text is too long (at most 100 kB). Put it on a public web page and give its "
                "address instead."
            )
        reviewers_found = _reviewers(reviewers)
        message = _message(message)
        due = self._check_due(due.strip(), now)
        prepared = PreparedRequest(
            title, address, text, reviewers_found, message, due, now,
            now + timedelta(days=PREPARED_DAYS),
        )  # fmt: skip
        return self._keep(prepared), prepared

    def keep_for_visitor(
        self,
        *,
        title: str,
        web_address: str,
        text: str,
        reviewers: Sequence[str],
        message: str,
        due: str,
        due_time: str = "",
        file_name: str = "",
        file_content: bytes | None = None,
        ai_models: Sequence[str] = (),
    ) -> str:
        """Keep a form filled in before signing in, file included, for an hour (ADR 0024).
        The form itself has checked what is cheap to check; the rest is checked on sending."""
        now = self._now()
        if len(text.encode("utf-8")) > MAX_VISITOR_TEXT_BYTES:
            raise InvalidPreparedRequest("The text is too long (limit: 400 kB).")
        if file_content is not None and len(file_content) > MAX_FILE_BYTES:
            raise InvalidPreparedRequest("That file is too large (limit: 10 MB).")
        prepared = PreparedRequest(
            _title(title), web_address.strip()[:2000], text.strip(), _reviewers(reviewers),
            _message(message), self._check_due(due.strip(), now), now,
            now + timedelta(hours=VISITOR_HOURS), VISITOR, (file_name or "")[:255],
            file_content, due_time.strip() if _TIME.fullmatch(due_time.strip()) else "",
            tuple(dict.fromkeys(m.strip()[:200] for m in ai_models if m.strip()))[:MAX_AI_MODELS],
        )  # fmt: skip
        return self._keep(prepared)

    def forget_expired(self) -> None:
        """Delete what has expired, files included. Runs every few minutes."""
        self._repo.delete_expired(self._now())

    def _keep(self, prepared: PreparedRequest) -> str:
        self._repo.delete_expired(prepared.created_at)
        if self._repo.count() >= MAX_PENDING:
            raise InvalidPreparedRequest(
                "Previewit has too many prepared requests waiting. Try again later."
            )
        if prepared.file_content is not None and self._repo.count_files() >= MAX_FILES_WAITING:
            raise InvalidPreparedRequest(
                "Previewit is keeping too many files for people who are signing in. Sign in "
                "first, then choose your file."
            )
        token = self._new_token()
        self._repo.add(token_hash(token), prepared)
        return token

    def open(self, token: str) -> PreparedRequest | None:
        """The request behind a link, or None if it expired, was sent or never existed."""
        prepared = self._repo.get(token_hash(token))
        if prepared is None or prepared.expires_at <= self._now():
            return None
        return prepared

    def used(self, token: str) -> None:
        """The person sent it: forget it."""
        self._repo.delete(token_hash(token))

    @staticmethod
    def _check_due(due: str, now: datetime) -> str:
        if not due:
            return ""
        try:
            day = date.fromisoformat(due)
        except ValueError:
            raise InvalidPreparedRequest("Write the due date as YYYY-MM-DD.") from None
        if day < now.date() - timedelta(days=1):  # a day of slack for time zones
            raise InvalidPreparedRequest("That due date has passed.")
        if day > now.date() + timedelta(days=365):
            raise InvalidPreparedRequest("Choose a due date within the next year.")
        return day.isoformat()


def _title(title: str) -> str:
    title = " ".join(title.split())
    if len(title) > MAX_TITLE:
        raise InvalidPreparedRequest(f"The title is too long (at most {MAX_TITLE} characters).")
    return title


def _reviewers(reviewers: Sequence[str]) -> tuple[str, ...]:
    found = parse_typed("\n".join(reviewers))
    if found.invalid:
        raise InvalidPreparedRequest(
            "These reviewers are not an address Previewit can use: "
            + ", ".join(found.invalid)
            + "."
        )
    if found.over_limit or len(found.emails) > MAX_EMAILS:
        raise InvalidPreparedRequest(f"Ask at most {MAX_EMAILS} reviewers at a time.")
    return tuple(e.value for e in found.emails)


def _message(message: str) -> str:
    message = message.strip()
    if len(message) > MAX_MESSAGE:
        raise InvalidPreparedRequest(f"The message is too long (at most {MAX_MESSAGE} characters).")
    return message
