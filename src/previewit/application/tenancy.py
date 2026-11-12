"""Organizations, spaces, members, groups and invite links, with authorisation."""

from __future__ import annotations

import secrets
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from previewit.application.ports import TenancyRepository, UserRepository
from previewit.application.verification import hash_token
from previewit.domain.identity import UserId
from previewit.domain.policy import DEFAULT_POLICY, Action, VerificationPolicy
from previewit.domain.tenancy import (
    CREATOR_ROLES,
    DEFAULT_ROLES,
    Group,
    GroupId,
    InvalidRole,
    Invite,
    Organization,
    OrgId,
    OrgRole,
    Permission,
    Preset,
    Role,
    Roles,
    Space,
    SpaceId,
    SpaceMember,
    can_grant,
    clean_name,
    coerce_roles,
    get_preset,
    permissions,
    role_permissions,
)

DEFAULT_INVITE_TTL = timedelta(days=7)


class NotFound(Exception):
    """Missing, or not visible to you: the two look the same on purpose."""


class Forbidden(Exception):
    """You can see this, but may not do that."""


class VerificationRequired(Exception):
    """The operator's policy requires a verified email address for this action."""

    def __init__(self, action: Action) -> None:
        super().__init__(f"a verified email is required to {action.value}")
        self.action = action


class NotAMember(Exception):
    pass


class InvalidInvite(Exception):
    pass


@dataclass(frozen=True)
class SpaceView:
    space: Space
    organization: Organization
    preset: Preset
    roles: Roles  # empty for an organization owner who is not a member
    permissions: frozenset[Permission]


@dataclass(frozen=True)
class MemberView:
    user_id: UserId
    display_name: str
    email: str | None  # only shown to people who may manage members
    roles: Roles


@dataclass(frozen=True)
class InvitePreview:
    space_name: str
    organization_name: str
    role_label: str


class TenancyService:
    def __init__(
        self,
        repo: TenancyRepository,
        users: UserRepository,
        new_id: Callable[[], str],
        now: Callable[[], datetime],
        *,
        policy: VerificationPolicy = DEFAULT_POLICY,
    ) -> None:
        self._policy = policy
        self._repo = repo
        self._users = users
        self._new_id = new_id
        self._now = now

    # -- organizations --------------------------------------------------------------

    def create_organization(self, actor: UserId, name: str, preset_key: str) -> Organization:
        self._need_verified(actor, Action.CREATE_ORGANIZATION)
        if get_preset(preset_key) is None:
            raise ValueError(f"unknown preset: {preset_key}")
        org = Organization(OrgId(self._new_id()), clean_name(name), preset_key)
        self._repo.add_org(org, actor)
        return org

    def my_organizations(self, actor: UserId) -> list[tuple[Organization, OrgRole]]:
        return self._repo.orgs_for_user(actor)

    def org_spaces(self, actor: UserId, org_id: OrgId) -> list[Space]:
        role = self._repo.org_role(org_id, actor)
        if role is None:
            raise NotFound
        if role is OrgRole.OWNER:
            return self._repo.spaces_in_org(org_id)
        return self._repo.spaces_of_member(org_id, actor)

    # -- spaces -------------------------------------------------------------------------

    def create_space(self, actor: UserId, org_id: OrgId, name: str) -> Space:
        role = self._repo.org_role(org_id, actor)
        org = self._repo.get_org(org_id)
        if role is None or org is None:
            raise NotFound
        if role is not OrgRole.OWNER:
            raise Forbidden
        space = Space(SpaceId(self._new_id()), org_id, clean_name(name))
        self._repo.add_space(space, SpaceMember(org_id, space.id, actor, CREATOR_ROLES))
        return space

    def my_spaces(self, actor: UserId) -> list[tuple[Space, Organization]]:
        spaces: dict[SpaceId, Space] = {s.id: s for s in self._repo.spaces_for_user(actor)}
        for org, role in self._repo.orgs_for_user(actor):
            if role is OrgRole.OWNER:
                spaces.update({s.id: s for s in self._repo.spaces_in_org(org.id)})
        result: list[tuple[Space, Organization]] = []
        for space in sorted(spaces.values(), key=lambda s: s.name.lower()):
            org = self._repo.get_org(space.org_id)
            if org is not None:
                result.append((space, org))
        return result

    def space_view(self, actor: UserId, space_id: SpaceId) -> SpaceView:
        return self._view(actor, space_id)

    # -- members ----------------------------------------------------------------------------

    def members(self, actor: UserId, space_id: SpaceId) -> list[MemberView]:
        view = self._view(actor, space_id)
        rows = self._repo.space_members(space_id)
        people = self._users.get_many([m.user_id for m in rows])
        show_email = Permission.MEMBERS_MANAGE in view.permissions
        result: list[MemberView] = []
        for member in rows:
            user = people.get(member.user_id)
            name = user.display_name if user else "Unknown"
            email = user.email.value if user and user.email and show_email else None
            result.append(MemberView(member.user_id, name, email, member.roles))
        return sorted(result, key=lambda m: (m.display_name.lower(), m.user_id))

    def change_roles(
        self, actor: UserId, space_id: SpaceId, target: UserId, roles: Iterable[str]
    ) -> None:
        view = self._require(actor, space_id, Permission.MEMBERS_MANAGE)
        granted = self._grantable(view, roles)
        member = self._member_or_raise(space_id, target)
        if target == actor and not granted >= member.roles:
            raise Forbidden  # you may add roles to yourself, never drop one (no lock-out)
        self._require_not_above(view, member)
        self._repo.set_space_member_roles(space_id, target, granted)

    def remove_member(self, actor: UserId, space_id: SpaceId, target: UserId) -> None:
        view = self._require(actor, space_id, Permission.MEMBERS_MANAGE)
        if target == actor:
            raise Forbidden
        member = self._member_or_raise(space_id, target)
        self._require_not_above(view, member)
        self._repo.remove_space_member(space_id, target)

    def admit(self, actor: UserId, space_id: SpaceId, roles: Iterable[Role]) -> Space:
        """Make `actor` a member through a link that someone vetted (a call for authors).

        Existing members keep their roles: a link never demotes anyone."""
        space = self._repo.get_space(space_id)
        if space is None:
            raise NotFound
        if self._repo.space_member(space_id, actor) is not None:
            return space
        self._need_verified(actor, Action.JOIN)
        self._repo.add_org_member(space.org_id, actor, OrgRole.MEMBER)
        self._repo.add_space_member(SpaceMember(space.org_id, space.id, actor, frozenset(roles)))
        return space

    # -- invites ------------------------------------------------------------------------------

    def create_invite(
        self,
        actor: UserId,
        space_id: SpaceId,
        *,
        roles: Iterable[str] | None = None,
        ttl: timedelta = DEFAULT_INVITE_TTL,
        max_uses: int | None = None,
    ) -> tuple[Invite, str]:
        view = self._require(actor, space_id, Permission.MEMBERS_INVITE)
        self._need_verified(actor, Action.INVITE)
        granted = DEFAULT_ROLES if roles is None else self._grantable(view, roles)
        token = secrets.token_urlsafe(32)
        invite = Invite(
            id=hash_token(token),
            org_id=view.space.org_id,
            space_id=space_id,
            roles=granted,
            created_by=actor,
            expires_at=self._now() + ttl,
            max_uses=max_uses,
            uses=0,
            revoked=False,
        )
        self._repo.add_invite(invite)
        return invite, token

    def invites(self, actor: UserId, space_id: SpaceId) -> list[Invite]:
        self._require(actor, space_id, Permission.MEMBERS_INVITE)
        return self._repo.invites_in_space(space_id)

    def revoke_invite(self, actor: UserId, space_id: SpaceId, invite_id: str) -> None:
        self._require(actor, space_id, Permission.MEMBERS_INVITE)
        invite = self._repo.get_invite(invite_id)
        if invite is None or invite.space_id != space_id:
            raise NotFound
        self._repo.revoke_invite(invite_id)

    def preview_invite(self, token: str) -> InvitePreview | None:
        found = self._live_invite(token)
        return None if found is None else found[1]

    def accept_invite(self, actor: UserId, token: str) -> Space:
        invite = self._repo.get_invite(hash_token(token)) if token else None
        space = self._repo.get_space(invite.space_id) if invite else None
        if invite is None or space is None:
            raise InvalidInvite
        if self._repo.space_member(space.id, actor) is not None:
            return space  # already in: no seat used, never a demotion, even if the link is spent
        if not invite.usable(self._now()):
            raise InvalidInvite
        self._need_verified(actor, Action.JOIN)  # checked before the link is used up
        if not self._repo.use_invite(invite.id, self._now()):
            raise InvalidInvite
        self._repo.add_org_member(space.org_id, actor, OrgRole.MEMBER)
        self._repo.add_space_member(SpaceMember(space.org_id, space.id, actor, invite.roles))
        return space

    # -- groups --------------------------------------------------------------------------------

    def groups(self, actor: UserId, space_id: SpaceId) -> list[Group]:
        self._view(actor, space_id)
        return self._repo.groups_in_space(space_id)

    def create_group(
        self, actor: UserId, space_id: SpaceId, name: str, members: Sequence[UserId] = ()
    ) -> Group:
        view = self._require(actor, space_id, Permission.GROUPS_MANAGE)
        for user_id in members:
            self._member_or_raise(space_id, user_id)
        group = Group(
            GroupId(self._new_id()),
            view.space.org_id,
            space_id,
            clean_name(name),
            frozenset(members),
        )
        self._repo.add_group(group)
        return group

    def rename_group(self, actor: UserId, space_id: SpaceId, group_id: GroupId, name: str) -> None:
        self._require(actor, space_id, Permission.GROUPS_MANAGE)
        self._group_or_raise(space_id, group_id)
        self._repo.rename_group(group_id, clean_name(name))

    def delete_group(self, actor: UserId, space_id: SpaceId, group_id: GroupId) -> None:
        self._require(actor, space_id, Permission.GROUPS_MANAGE)
        self._group_or_raise(space_id, group_id)
        self._repo.delete_group(group_id)

    def add_to_group(
        self, actor: UserId, space_id: SpaceId, group_id: GroupId, user_id: UserId
    ) -> None:
        self._require(actor, space_id, Permission.GROUPS_MANAGE)
        self._group_or_raise(space_id, group_id)
        self._member_or_raise(space_id, user_id)
        self._repo.add_group_member(group_id, user_id)

    def remove_from_group(
        self, actor: UserId, space_id: SpaceId, group_id: GroupId, user_id: UserId
    ) -> None:
        self._require(actor, space_id, Permission.GROUPS_MANAGE)
        self._group_or_raise(space_id, group_id)
        self._repo.remove_group_member(group_id, user_id)

    # -- helpers ---------------------------------------------------------------------------------

    def _need_verified(self, actor: UserId, action: Action) -> None:
        if action not in self._policy.required_for:
            return
        user = self._users.get(actor)
        if user is None or not self._policy.allows(user, action):
            raise VerificationRequired(action)

    def _view(self, actor: UserId, space_id: SpaceId) -> SpaceView:
        space = self._repo.get_space(space_id)
        org = self._repo.get_org(space.org_id) if space else None
        if space is None or org is None:
            raise NotFound
        preset = _preset_of(org)
        member = self._repo.space_member(space_id, actor)
        roles: Roles = member.roles if member else frozenset()
        granted = permissions(self._repo.org_role(org.id, actor), roles)
        if Permission.SPACE_VIEW not in granted:
            raise NotFound  # outsiders cannot tell the space exists
        return SpaceView(space, org, preset, roles, granted)

    def _require(self, actor: UserId, space_id: SpaceId, needed: Permission) -> SpaceView:
        view = self._view(actor, space_id)
        if needed not in view.permissions:
            raise Forbidden
        return view

    def _member_or_raise(self, space_id: SpaceId, user_id: UserId) -> SpaceMember:
        member = self._repo.space_member(space_id, user_id)
        if member is None:
            raise NotAMember
        return member

    @staticmethod
    def _require_not_above(view: SpaceView, member: SpaceMember) -> None:
        if not role_permissions(member.roles) <= view.permissions:
            raise Forbidden

    @staticmethod
    def _grantable(view: SpaceView, names: Iterable[str]) -> Roles:
        """The roles named, if they exist and are no stronger than the actor's own."""
        try:
            roles = coerce_roles(names)
        except InvalidRole:
            raise Forbidden from None
        if not can_grant(view.permissions, roles):
            raise Forbidden
        return roles

    def _group_or_raise(self, space_id: SpaceId, group_id: GroupId) -> Group:
        group = self._repo.get_group(group_id)
        if group is None or group.space_id != space_id:
            raise NotFound
        return group

    def _live_invite(self, token: str) -> tuple[Invite, InvitePreview] | None:
        if not token:
            return None
        invite = self._repo.get_invite(hash_token(token))
        if invite is None or not invite.usable(self._now()):
            return None
        space = self._repo.get_space(invite.space_id)
        org = self._repo.get_org(invite.org_id)
        if space is None or org is None:
            return None
        label = _preset_of(org).role_label(invite.roles).capitalize()
        return invite, InvitePreview(space.name, org.name, label)


def _preset_of(org: Organization) -> Preset:
    preset = get_preset(org.preset_key)
    if preset is None:
        raise RuntimeError(f"organization {org.id} uses unknown preset {org.preset_key}")
    return preset
