"""Organizations (tenants), spaces, groups, invites and who may do what.

Roles are data supplied by presets; the core never names a concrete role.
"""

from __future__ import annotations

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


class OrgRole(StrEnum):
    OWNER = "owner"  # all permissions in every space of the organization
    MEMBER = "member"


@dataclass(frozen=True)
class RoleDef:
    key: str
    label: str
    permissions: frozenset[Permission]


@dataclass(frozen=True)
class Preset:
    """Vocabulary and role set for a kind of organization."""

    key: str
    label: str
    roles: tuple[RoleDef, ...]
    creator_role: str  # role of whoever creates a space
    default_role: str  # role given to people who join through a link
    vocabulary: dict[str, str] = field(default_factory=dict[str, str], compare=False)

    def role(self, key: str) -> RoleDef | None:
        return next((r for r in self.roles if r.key == key), None)

    def word(self, concept: str) -> str:
        """The preset's word for a core concept; the concept's own name if it has none."""
        return self.vocabulary.get(concept, concept)


P = Permission

EDUCATION = Preset(
    key="education",
    label="Education",
    roles=(
        RoleDef("teacher", "Teacher", frozenset(Permission)),
        RoleDef(
            "assistant",
            "Teaching assistant",
            frozenset({P.SPACE_VIEW, P.MEMBERS_INVITE, P.GROUPS_MANAGE}),
        ),
        RoleDef("student", "Student", frozenset({P.SPACE_VIEW})),
    ),
    creator_role="teacher",
    default_role="student",
    vocabulary={
        "organization": "school",
        "space": "course",
        "spaces": "courses",
        "member": "participant",
        "members": "participants",
        "group": "group",
        "groups": "groups",
    },
)

PRESETS: dict[str, Preset] = {EDUCATION.key: EDUCATION}


def get_preset(key: str) -> Preset | None:
    return PRESETS.get(key)


def permissions(
    preset: Preset, org_role: OrgRole | None, space_role: str | None
) -> frozenset[Permission]:
    """What someone may do in a space, from their organization role and space role."""
    if org_role is OrgRole.OWNER:
        return frozenset(Permission)
    if space_role is None:
        return frozenset()
    role = preset.role(space_role)
    return role.permissions if role else frozenset()


def can_grant(preset: Preset, actor: frozenset[Permission], role_key: str) -> bool:
    """No privilege escalation: you may only hand out roles no stronger than your own."""
    role = preset.role(role_key)
    return role is not None and role.permissions <= actor


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
    role_key: str


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
    role_key: str
    created_by: UserId
    expires_at: datetime
    max_uses: int | None
    uses: int
    revoked: bool

    def usable(self, now: datetime) -> bool:
        if self.revoked or self.expires_at <= now:
            return False
        return self.max_uses is None or self.uses < self.max_uses
