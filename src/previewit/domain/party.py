"""A Party is whoever authors a submission or writes a review: a person or a group."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class UserParty:
    user_id: str


@dataclass(frozen=True)
class GroupParty:
    group_id: str


Party = UserParty | GroupParty
