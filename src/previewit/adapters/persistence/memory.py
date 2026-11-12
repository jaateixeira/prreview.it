"""In-memory repositories: fast fakes that follow the same contract as the SQL ones."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime

from previewit.application.ports import DuplicateEmail, DuplicateIdentity, EmailToken
from previewit.domain.identity import Email, IdentityKey, User, UserId
from previewit.domain.tenancy import (
    Group,
    GroupId,
    Invite,
    Organization,
    OrgId,
    OrgRole,
    Roles,
    Space,
    SpaceId,
    SpaceMember,
)


class InMemoryUserRepository:
    def __init__(self) -> None:
        self._users: dict[UserId, User] = {}
        self._hashes: dict[UserId, str] = {}
        self._by_identity: dict[IdentityKey, UserId] = {}

    def get(self, user_id: UserId) -> User | None:
        return self._users.get(user_id)

    def get_many(self, user_ids: Sequence[UserId]) -> dict[UserId, User]:
        return {uid: self._users[uid] for uid in user_ids if uid in self._users}

    def find_by_identity(self, key: IdentityKey) -> User | None:
        user_id = self._by_identity.get(key)
        return self._users[user_id] if user_id else None

    def find_by_email(self, email: Email) -> User | None:
        return next((u for u in self._users.values() if u.email == email), None)

    def add_user(self, user: User, password_hash: str | None) -> None:
        if user.email is not None and self.find_by_email(user.email) is not None:
            raise DuplicateEmail
        if any(key in self._by_identity for key in user.identities):
            raise DuplicateIdentity
        self._users[user.id] = replace(user, has_password=password_hash is not None)
        if password_hash is not None:
            self._hashes[user.id] = password_hash
        for key in user.identities:
            self._by_identity[key] = user.id

    def add_identity(
        self,
        user_id: UserId,
        key: IdentityKey,
        *,
        clear_password: bool = False,
        verify_email: bool = False,
    ) -> None:
        if key in self._by_identity:
            raise DuplicateIdentity
        user = self._users[user_id]
        if clear_password:
            self._hashes.pop(user_id, None)
        self._users[user_id] = replace(
            user,
            identities=user.identities | {key},
            has_password=user_id in self._hashes,
            email_verified=user.email_verified or (verify_email and user.email is not None),
        )
        self._by_identity[key] = user_id

    def get_password_hash(self, user_id: UserId) -> str | None:
        return self._hashes.get(user_id)

    def mark_email_verified(self, user_id: UserId, email: Email) -> bool:
        user = self._users.get(user_id)
        if user is None or user.email != email:
            return False
        self._users[user_id] = replace(user, email_verified=True)
        return True

    def set_password_hash(self, user_id: UserId, password_hash: str) -> None:
        self._hashes[user_id] = password_hash
        self._users[user_id] = replace(self._users[user_id], has_password=True)


class InMemoryEmailTokenRepository:
    def __init__(self) -> None:
        # hash -> (user, email, created, expires, used)
        self._rows: dict[str, tuple[UserId, Email, datetime, datetime, bool]] = {}

    def add(
        self,
        token_hash: str,
        user_id: UserId,
        email: Email,
        created_at: datetime,
        expires_at: datetime,
    ) -> None:
        self._rows[token_hash] = (user_id, email, created_at, expires_at, False)

    def delete_for_user(self, user_id: UserId) -> None:
        self._rows = {h: r for h, r in self._rows.items() if r[0] != user_id}

    def last_created_at(self, user_id: UserId) -> datetime | None:
        times = [r[2] for r in self._rows.values() if r[0] == user_id]
        return max(times) if times else None

    def consume(self, token_hash: str, now: datetime) -> EmailToken | None:
        row = self._rows.get(token_hash)
        if row is None or row[4] or row[3] <= now:
            return None
        self._rows[token_hash] = (*row[:4], True)
        return EmailToken(row[0], row[1])


class InMemoryTenancyRepository:
    def __init__(self) -> None:
        self._orgs: dict[OrgId, Organization] = {}
        self._org_members: dict[tuple[OrgId, UserId], OrgRole] = {}
        self._spaces: dict[SpaceId, Space] = {}
        self._space_members: dict[tuple[SpaceId, UserId], SpaceMember] = {}
        self._groups: dict[GroupId, Group] = {}
        self._invites: dict[str, Invite] = {}

    # organizations
    def add_org(self, org: Organization, owner: UserId) -> None:
        self._orgs[org.id] = org
        self._org_members[(org.id, owner)] = OrgRole.OWNER

    def get_org(self, org_id: OrgId) -> Organization | None:
        return self._orgs.get(org_id)

    def org_role(self, org_id: OrgId, user_id: UserId) -> OrgRole | None:
        return self._org_members.get((org_id, user_id))

    def add_org_member(self, org_id: OrgId, user_id: UserId, role: OrgRole) -> None:
        self._org_members.setdefault((org_id, user_id), role)

    def orgs_for_user(self, user_id: UserId) -> list[tuple[Organization, OrgRole]]:
        found = [
            (self._orgs[org_id], role)
            for (org_id, uid), role in self._org_members.items()
            if uid == user_id
        ]
        return sorted(found, key=lambda pair: pair[0].name.lower())

    # spaces
    def add_space(self, space: Space, creator: SpaceMember) -> None:
        self._spaces[space.id] = space
        self._space_members[(space.id, creator.user_id)] = creator

    def get_space(self, space_id: SpaceId) -> Space | None:
        return self._spaces.get(space_id)

    def spaces_in_org(self, org_id: OrgId) -> list[Space]:
        found = [s for s in self._spaces.values() if s.org_id == org_id]
        return sorted(found, key=lambda s: s.name.lower())

    def spaces_of_member(self, org_id: OrgId, user_id: UserId) -> list[Space]:
        return [s for s in self.spaces_in_org(org_id) if (s.id, user_id) in self._space_members]

    def spaces_for_user(self, user_id: UserId) -> list[Space]:
        found = [s for s in self._spaces.values() if (s.id, user_id) in self._space_members]
        return sorted(found, key=lambda s: s.name.lower())

    def space_member(self, space_id: SpaceId, user_id: UserId) -> SpaceMember | None:
        return self._space_members.get((space_id, user_id))

    def space_members(self, space_id: SpaceId) -> list[SpaceMember]:
        return [m for (sid, _), m in self._space_members.items() if sid == space_id]

    def add_space_member(self, member: SpaceMember) -> None:
        self._space_members.setdefault((member.space_id, member.user_id), member)

    def set_space_member_roles(self, space_id: SpaceId, user_id: UserId, roles: Roles) -> None:
        current = self._space_members[(space_id, user_id)]
        self._space_members[(space_id, user_id)] = replace(current, roles=roles)

    def remove_space_member(self, space_id: SpaceId, user_id: UserId) -> None:
        self._space_members.pop((space_id, user_id), None)
        for group in self.groups_in_space(space_id):
            self.remove_group_member(group.id, user_id)

    # groups
    def add_group(self, group: Group) -> None:
        self._groups[group.id] = group

    def get_group(self, group_id: GroupId) -> Group | None:
        return self._groups.get(group_id)

    def groups_in_space(self, space_id: SpaceId) -> list[Group]:
        found = [g for g in self._groups.values() if g.space_id == space_id]
        return sorted(found, key=lambda g: g.name.lower())

    def rename_group(self, group_id: GroupId, name: str) -> None:
        self._groups[group_id] = replace(self._groups[group_id], name=name)

    def delete_group(self, group_id: GroupId) -> None:
        self._groups.pop(group_id, None)

    def add_group_member(self, group_id: GroupId, user_id: UserId) -> None:
        group = self._groups[group_id]
        self._groups[group_id] = replace(group, members=group.members | {user_id})

    def remove_group_member(self, group_id: GroupId, user_id: UserId) -> None:
        group = self._groups[group_id]
        self._groups[group_id] = replace(group, members=group.members - {user_id})

    # invites
    def add_invite(self, invite: Invite) -> None:
        self._invites[invite.id] = invite

    def get_invite(self, invite_id: str) -> Invite | None:
        return self._invites.get(invite_id)

    def invites_in_space(self, space_id: SpaceId) -> list[Invite]:
        found = [i for i in self._invites.values() if i.space_id == space_id]
        return sorted(found, key=lambda i: i.expires_at)

    def revoke_invite(self, invite_id: str) -> None:
        self._invites[invite_id] = replace(self._invites[invite_id], revoked=True)

    def use_invite(self, invite_id: str, now: datetime) -> bool:
        invite = self._invites.get(invite_id)
        if invite is None or not invite.usable(now):
            return False
        self._invites[invite_id] = replace(invite, uses=invite.uses + 1)
        return True
