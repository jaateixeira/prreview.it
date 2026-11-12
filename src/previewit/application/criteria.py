"""The CriterionType plugin API: kinds of question a rubric can ask a reviewer.

A plugin declares the settings a rubric author fills in (`fields`), turns the submitted
strings into a normalised config, and renders the input a reviewer will see. The core never
branches on a type key.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Literal, Protocol, runtime_checkable


class CriterionError(ValueError):
    """The settings are not acceptable; the message is shown to the rubric author."""


@dataclass(frozen=True)
class Field:
    name: str
    label: str
    kind: Literal["int", "lines"]
    default: str = ""
    help: str = ""


@runtime_checkable
class CriterionType(Protocol):
    key: str
    label: str
    fields: tuple[Field, ...]

    def parse_config(self, raw: Mapping[str, str]) -> dict[str, Any]:
        """Validate the author's settings (all strings). Raise CriterionError."""
        ...

    def to_form(self, config: Mapping[str, Any]) -> dict[str, str]:
        """The config as the strings `parse_config` accepts, to prefill the edit form."""
        ...

    def max_score(self, config: Mapping[str, Any]) -> int | None:
        """The highest score, or None when the answer is not a score."""
        ...

    def describe(self, config: Mapping[str, Any]) -> str:
        """One line for lists, for example `1 to 5`."""
        ...

    def render_html(self, config: Mapping[str, Any], name: str, value: str = "") -> str:
        """Safe HTML for the reviewer's input, named `name`, showing `value` if given.
        Escape every string."""
        ...

    def check_answer(self, config: Mapping[str, Any], raw: str) -> str:
        """Validate a reviewer's answer (a string from a form). Return it normalised, or ""
        for no answer. Raise CriterionError with a message the reviewer can act on."""
        ...

    def score(self, config: Mapping[str, Any], value: str) -> int | None:
        """The numeric score of a normalised answer, or None when it is not a score."""
        ...


class UnknownCriterionType(KeyError):
    pass


class CriterionRegistry:
    def __init__(self, types: Iterable[CriterionType] = ()) -> None:
        self._types: dict[str, CriterionType] = {}
        for t in types:
            self.register(t)

    def register(self, criterion_type: CriterionType) -> None:
        if criterion_type.key in self._types:
            raise ValueError(f"criterion type {criterion_type.key!r} is registered twice")
        self._types[criterion_type.key] = criterion_type

    def get(self, key: str) -> CriterionType:
        try:
            return self._types[key]
        except KeyError:
            raise UnknownCriterionType(key) from None

    def all(self) -> list[CriterionType]:
        return list(self._types.values())
