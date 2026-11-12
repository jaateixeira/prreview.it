"""Rubrics: an ordered list of criteria that reviewers answer, reusable across calls.

What a criterion *is* (a 1-4 scale, yes/no, free text, ...) is decided by a CriterionType
plugin; the domain stores its key and its normalised configuration and knows nothing more.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, NewType

from previewit.domain.identity import UserId
from previewit.domain.tenancy import OrgId, SpaceId

RubricId = NewType("RubricId", str)
CriterionId = NewType("CriterionId", str)

MAX_CRITERIA = 30
MAX_NAME_LENGTH = 100
MAX_TITLE_LENGTH = 200
MAX_GUIDANCE_LENGTH = 1000
MAX_WEIGHT = 100


class InvalidRubric(ValueError):
    pass


def clean_rubric_name(value: str) -> str:
    name = " ".join(value.split())
    if not name or len(name) > MAX_NAME_LENGTH:
        raise InvalidRubric(f"a rubric name must be 1-{MAX_NAME_LENGTH} characters")
    return name


def clean_criterion_title(value: str) -> str:
    title = " ".join(value.split())
    if not title or len(title) > MAX_TITLE_LENGTH:
        raise InvalidRubric(f"a criterion needs a title of 1-{MAX_TITLE_LENGTH} characters")
    return title


def clean_guidance(value: str) -> str:
    text = value.replace("\r\n", "\n").strip()
    if len(text) > MAX_GUIDANCE_LENGTH:
        raise InvalidRubric(f"guidance may have at most {MAX_GUIDANCE_LENGTH} characters")
    return text


def clean_weight(value: int) -> int:
    if not 0 <= value <= MAX_WEIGHT:
        raise InvalidRubric(f"a weight must be between 0 and {MAX_WEIGHT}")
    return value


@dataclass(frozen=True)
class Rubric:
    id: RubricId
    org_id: OrgId
    space_id: SpaceId
    name: str
    description: str
    created_by: UserId


@dataclass(frozen=True)
class Criterion:
    id: CriterionId
    org_id: OrgId
    rubric_id: RubricId
    position: int  # 0-based; ties are broken by id
    title: str
    guidance: str  # shown to reviewers next to the input
    type_key: str  # which CriterionType plugin
    config: dict[str, Any]  # normalised by that plugin
    weight: int  # 0 = feedback only, not scored
    required: bool


def ordered(criteria: Sequence[Criterion]) -> list[Criterion]:
    return sorted(criteria, key=lambda c: (c.position, c.id))


# --- templates: starting points an organization kind offers ---------------------------------


@dataclass(frozen=True)
class CriterionTemplate:
    title: str
    guidance: str
    type_key: str
    raw_config: dict[str, str] = field(default_factory=dict[str, str])  # as a form would send it
    weight: int = 1
    required: bool = True


@dataclass(frozen=True)
class RubricTemplate:
    key: str
    name: str
    description: str
    criteria: tuple[CriterionTemplate, ...]


_LEVELS = (
    "Not yet | The idea is missing or hard to follow\n"
    "Developing | Present, but needs more work\n"
    "Good | Clear and mostly convincing\n"
    "Excellent | Clear, convincing and well supported"
)

EDUCATION_TEMPLATES = (
    RubricTemplate(
        "essay-feedback",
        "Essay feedback",
        "Clarity, argument and constructive comments for a written piece.",
        (
            CriterionTemplate("Clarity", "Is it easy to follow?", "levels", {"levels": _LEVELS}),
            CriterionTemplate(
                "Argument", "Is the main point supported?", "levels", {"levels": _LEVELS}, 2
            ),
            CriterionTemplate("What worked well?", "Name something specific.", "text", weight=0),
            CriterionTemplate(
                "What could be improved?", "Suggest one concrete next step.", "text", weight=0
            ),
        ),
    ),
    RubricTemplate(
        "quick-check",
        "Quick check",
        "A short yes/no check and one comment.",
        (
            CriterionTemplate("Meets the assignment", "Does it do what was asked?", "yes_no"),
            CriterionTemplate(
                "Overall score", "1 is low, 5 is high.", "numeric", {"min": "1", "max": "5"}
            ),
            CriterionTemplate("Comment", "One thing the author should know.", "text", weight=0),
        ),
    ),
)

TEMPLATES: dict[str, tuple[RubricTemplate, ...]] = {"education": EDUCATION_TEMPLATES}


def templates_for(preset_key: str) -> tuple[RubricTemplate, ...]:
    return TEMPLATES.get(preset_key, ())
