"""Directional anonymity policy.

Instead of fixed "single/double blind" modes, each direction is an independent switch.
Presets cover the classic modes, including single-blind in *either* direction.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class RevealAt(Enum):
    NEVER = "never"
    ROUND_CLOSE = "round_close"
    DECISION = "decision"


class Viewer(Enum):
    ORGANIZER = "organizer"
    AUTHOR = "author"
    REVIEWER = "reviewer"
    OTHER_REVIEWER = "other_reviewer"


@dataclass(frozen=True)
class AnonymityPolicy:
    author_visible_to_reviewer: bool
    reviewer_visible_to_author: bool
    reviewer_visible_to_other_reviewers: bool
    reveal_at: RevealAt = RevealAt.NEVER

    @classmethod
    def open(cls) -> AnonymityPolicy:
        return cls(True, True, True)

    @classmethod
    def single_blind_reviewers_hidden(cls) -> AnonymityPolicy:
        """Authors do not learn who reviewed them (the common case)."""
        return cls(True, False, True)

    @classmethod
    def single_blind_authors_hidden(cls) -> AnonymityPolicy:
        """Reviewers do not learn who wrote the work; authors know their reviewers."""
        return cls(False, True, True)

    @classmethod
    def double_blind(cls) -> AnonymityPolicy:
        return cls(False, False, False)

    def may_see_author(self, viewer: Viewer, *, revealed: bool = False) -> bool:
        """Can ``viewer`` see who authored the submission?"""
        if revealed or viewer in (Viewer.ORGANIZER, Viewer.AUTHOR):
            return True
        return self.author_visible_to_reviewer

    def may_see_reviewer(self, viewer: Viewer, *, revealed: bool = False) -> bool:
        """Can ``viewer`` see who wrote a given review?"""
        if revealed or viewer in (Viewer.ORGANIZER, Viewer.REVIEWER):
            return True
        if viewer is Viewer.AUTHOR:
            return self.reviewer_visible_to_author
        return self.reviewer_visible_to_other_reviewers


def is_revealed(reveal_at: RevealAt, *, round_closed: bool, decided: bool) -> bool:
    """Whether identities are lifted, given where the round/decision currently stands."""
    if reveal_at is RevealAt.ROUND_CLOSE:
        return round_closed
    if reveal_at is RevealAt.DECISION:
        return decided
    return False
