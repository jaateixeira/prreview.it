"""Organizations (tenants), spaces, groups, invites and who may do what.

Three fixed roles per space: organizer, author, reviewer (ADR 0017). A member holds a set of
them. Presets only rename them; they do not define roles.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import NewType

from previewit.domain.identity import UserId

OrgId = NewType("OrgId", str)
SpaceId = NewType("SpaceId", str)
GroupId = NewType("GroupId", str)

MAX_NAME_LENGTH = 100


class InvalidName(ValueError):
    pass


def clean_name(value: str) -> str:
    name = " ".join(value.split())
    if not name or len(name) > MAX_NAME_LENGTH:
        raise InvalidName(f"a name must be 1-{MAX_NAME_LENGTH} characters")
    return name


class Permission(StrEnum):
    SPACE_VIEW = "space.view"
    SPACE_MANAGE = "space.manage"
    MEMBERS_INVITE = "members.invite"
    MEMBERS_MANAGE = "members.manage"
    GROUPS_MANAGE = "groups.manage"
    CALLS_MANAGE = "calls.manage"
    SUBMIT = "submissions.create"
    SUBMISSIONS_VIEW_ALL = "submissions.view_all"
    RUBRICS_MANAGE = "rubrics.manage"
    ROUNDS_MANAGE = "rounds.manage"


class OrgRole(StrEnum):
    OWNER = "owner"  # all permissions in every space of the organization
    MEMBER = "member"


class InvalidRole(ValueError):
    pass


class Role(StrEnum):
    ORGANIZER = "organizer"  # calls for authors and reviewers, runs rounds, reads everything
    AUTHOR = "author"  # submits work to calls
    REVIEWER = "reviewer"  # reviews the work of authors, on invitation or allocation


Roles = frozenset[Role]


@dataclass(frozen=True)
class Preset:
    """Vocabulary for a kind of organization. It renames concepts and roles; it adds none."""

    key: str
    label: str
    vocabulary: dict[str, str] = field(default_factory=dict[str, str], compare=False)

    def word(self, concept: str) -> str:
        """The preset's word for a core concept; the concept's own name if it has none."""
        return self.vocabulary.get(concept, concept)

    def role_label(self, roles: Iterable[Role]) -> str:
        return ", ".join(self.word(r.value) for r in sorted(roles))


P = Permission

EDUCATION = Preset(
    key="education",
    label="Education",
    vocabulary={
        "organization": "school",
        "space": "course",
        "spaces": "courses",
        "member": "participant",
        "members": "participants",
        "organizer": "teacher",
        "author": "author",
        "reviewer": "reviewer",
        "group": "group",
        "groups": "groups",
        "call": "assignment",
        "calls": "assignments",
        "submission": "submission",
        "submissions": "submissions",
    },
)

# For anyone who just wants a review: no school words. Its Space is a "review space".
GENERAL = Preset(
    key="general",
    label="General",
    vocabulary={"space": "review space", "spaces": "review spaces"},
)

PRESETS: dict[str, Preset] = {EDUCATION.key: EDUCATION, GENERAL.key: GENERAL}


def get_preset(key: str) -> Preset | None:
    return PRESETS.get(key)


ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.ORGANIZER: frozenset(Permission),
    Role.AUTHOR: frozenset({P.SPACE_VIEW, P.SUBMIT}),
    Role.REVIEWER: frozenset({P.SPACE_VIEW}),
}

CREATOR_ROLES: Roles = frozenset({Role.ORGANIZER})  # whoever creates a space
DEFAULT_ROLES: Roles = frozenset({Role.AUTHOR, Role.REVIEWER})  # people who join through a link


def role_permissions(roles: Iterable[Role]) -> frozenset[Permission]:
    granted: set[Permission] = set()
    for role in roles:
        granted |= ROLE_PERMISSIONS[role]
    return frozenset(granted)


def format_roles(roles: Iterable[Role]) -> str:
    """The stored form: sorted, comma separated."""
    return ",".join(sorted(r.value for r in roles))


def coerce_roles(values: Iterable[str]) -> Roles:
    """Roles from their names. At least one, and every name must be a role."""
    try:
        roles = frozenset(Role(v) for v in values)
    except ValueError:
        raise InvalidRole("unknown role") from None
    if not roles:
        raise InvalidRole("a member holds at least one role")
    return roles


def parse_roles(value: str) -> Roles:
    return coerce_roles(v for v in value.split(",") if v.strip())


def permissions(org_role: OrgRole | None, roles: Roles) -> frozenset[Permission]:
    """What someone may do in a space, from their organization role and space roles."""
    if org_role is OrgRole.OWNER:
        return frozenset(Permission)
    return role_permissions(roles)


def can_grant(actor: frozenset[Permission], roles: Roles) -> bool:
    """No privilege escalation: you may only hand out roles no stronger than your own."""
    return bool(roles) and role_permissions(roles) <= actor


@dataclass(frozen=True)
class Organization:
    id: OrgId
    name: str
    preset_key: str


@dataclass(frozen=True)
class Space:
    id: SpaceId
    org_id: OrgId
    name: str


@dataclass(frozen=True)
class SpaceMember:
    org_id: OrgId
    space_id: SpaceId
    user_id: UserId
    roles: Roles


@dataclass(frozen=True)
class Group:
    id: GroupId
    org_id: OrgId
    space_id: SpaceId
    name: str
    members: frozenset[UserId]


@dataclass(frozen=True)
class Invite:
    """An invitation link. `id` is the SHA-256 of the secret in the link."""

    id: str
    org_id: OrgId
    space_id: SpaceId
    roles: Roles
    created_by: UserId
    expires_at: datetime
    max_uses: int | None
    uses: int
    revoked: bool

    def usable(self, now: datetime) -> bool:
        if self.revoked or self.expires_at <= now:
            return False
        return self.max_uses is None or self.uses < self.max_uses
