"""Which actions need a verified email address. The operator chooses in the config file."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from previewit.domain.identity import User


class Action(StrEnum):
    CREATE_ORGANIZATION = "create_organization"
    INVITE = "invite"  # create invitation links
    JOIN = "join"  # join a space through a link
    SUBMIT = "submit"
    REVIEW = "review"


@dataclass(frozen=True)
class VerificationPolicy:
    required_for: frozenset[Action]

    def allows(self, user: User, action: Action) -> bool:
        if action not in self.required_for:
            return True
        return user.email is not None and user.email_verified


# Unverified users may be invited, join and submit, but cannot review.
DEFAULT_POLICY = VerificationPolicy(frozenset({Action.REVIEW}))


def parse_actions(names: Iterable[str]) -> frozenset[Action]:
    valid = ", ".join(a.value for a in Action)
    result: set[Action] = set()
    for name in names:
        try:
            result.add(Action(name.strip()))
        except ValueError:
            raise ValueError(f"unknown action {name!r}; valid actions: {valid}") from None
    return frozenset(result)
