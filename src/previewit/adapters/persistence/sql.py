"""SQL implementation of the user repository (SQLAlchemy Core; SQLite and PostgreSQL)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import Engine, and_, delete, func, insert, or_, select, update
from sqlalchemy.engine import Connection, Row
from sqlalchemy.exc import IntegrityError

from previewit.adapters.persistence.tables import (
    email_verifications,
    external_identities,
    group_members,
    groups,
    invites,
    org_memberships,
    organizations,
    space_members,
    spaces,
    users,
)
from previewit.application.ports import DuplicateEmail, DuplicateIdentity, EmailToken
from previewit.domain.identity import Email, IdentityKey, Provider, User, UserId
from previewit.domain.tenancy import (
    Group,
    GroupId,
    Invite,
    Organization,
    OrgId,
    OrgRole,
    Space,
    SpaceId,
    SpaceMember,
)


class SqlUserRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    # -- reads ---------------------------------------------------------------

    def get(self, user_id: UserId) -> User | None:
        with self._engine.connect() as conn:
            return self._load(conn, users.c.id == user_id)

    def get_many(self, user_ids: Sequence[UserId]) -> dict[UserId, User]:
        # Few members per space: a loop of indexed lookups keeps this simple.
        found = (self.get(uid) for uid in dict.fromkeys(user_ids))
        return {u.id: u for u in found if u is not None}

    def find_by_email(self, email: Email) -> User | None:
        with self._engine.connect() as conn:
            return self._load(conn, users.c.email == email.value)

    def find_by_identity(self, key: IdentityKey) -> User | None:
        with self._engine.connect() as conn:
            row = conn.execute(select(external_identities.c.user_id).where(_is(key))).first()
            return self._load(conn, users.c.id == row[0]) if row else None

    def get_password_hash(self, user_id: UserId) -> str | None:
        with self._engine.connect() as conn:
            return conn.execute(
                select(users.c.password_hash).where(users.c.id == user_id)
            ).scalar_one_or_none()

    # -- writes --------------------------------------------------------------

    def add_user(self, user: User, password_hash: str | None) -> None:
        try:
            with self._engine.begin() as conn:
                conn.execute(
                    insert(users).values(
                        id=user.id,
                        email=user.email.value if user.email else None,
                        email_verified=user.email_verified,
                        display_name=user.display_name,
                        password_hash=password_hash,
                    )
                )
                for key in user.identities:
                    conn.execute(insert(external_identities).values(**_values(key, user.id)))
        except IntegrityError:
            # The transaction rolled back, so a fresh look tells us which rule was hit.
            with self._engine.connect() as conn:
                if any(self._identity_exists(conn, key) for key in user.identities):
                    raise DuplicateIdentity from None
            raise DuplicateEmail from None

    def add_identity(
        self,
        user_id: UserId,
        key: IdentityKey,
        *,
        clear_password: bool = False,
        verify_email: bool = False,
    ) -> None:
        try:
            with self._engine.begin() as conn:
                conn.execute(insert(external_identities).values(**_values(key, user_id)))
                changes: dict[str, object] = {}
                if clear_password:
                    changes["password_hash"] = None
                if verify_email:
                    changes["email_verified"] = True
                if changes:
                    stmt = update(users).where(users.c.id == user_id)
                    if verify_email:
                        # an account without an email has nothing to verify
                        stmt = stmt.where(users.c.email.is_not(None))
                    conn.execute(stmt.values(**changes))
        except IntegrityError:
            raise DuplicateIdentity from None

    def mark_email_verified(self, user_id: UserId, email: Email) -> bool:
        with self._engine.begin() as conn:
            result = conn.execute(
                update(users)
                .where(users.c.id == user_id, users.c.email == email.value)
                .values(email_verified=True)
            )
            return result.rowcount == 1

    def set_password_hash(self, user_id: UserId, password_hash: str) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                update(users).where(users.c.id == user_id).values(password_hash=password_hash)
            )

    # -- helpers -------------------------------------------------------------

    @staticmethod
    def _identity_exists(conn: Connection, key: IdentityKey) -> bool:
        return (
            conn.execute(select(external_identities.c.user_id).where(_is(key))).first() is not None
        )

    @staticmethod
    def _load(conn: Connection, where) -> User | None:
        row: Row | None = conn.execute(select(users).where(where)).first()
        if row is None:
            return None
        keys = conn.execute(
            select(external_identities.c.provider, external_identities.c.subject).where(
                external_identities.c.user_id == row.id
            )
        ).all()
        return User(
            id=UserId(row.id),
            display_name=row.display_name,
            email=Email(row.email) if row.email else None,
            email_verified=bool(row.email_verified),
            identities=frozenset(IdentityKey(Provider(p), s) for p, s in keys),
            has_password=row.password_hash is not None,
        )


def _is(key: IdentityKey):
    return and_(
        external_identities.c.provider == key.provider.value,
        external_identities.c.subject == key.subject,
    )


def _values(key: IdentityKey, user_id: str) -> dict[str, str]:
    return {"provider": key.provider.value, "subject": key.subject, "user_id": user_id}


class SqlEmailTokenRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def add(
        self,
        token_hash: str,
        user_id: UserId,
        email: Email,
        created_at: datetime,
        expires_at: datetime,
    ) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                insert(email_verifications).values(
                    token_hash=token_hash,
                    user_id=user_id,
                    email=email.value,
                    created_at=created_at,
                    expires_at=expires_at,
                )
            )

    def delete_for_user(self, user_id: UserId) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                delete(email_verifications).where(email_verifications.c.user_id == user_id)
            )

    def last_created_at(self, user_id: UserId) -> datetime | None:
        with self._engine.connect() as conn:
            value = conn.execute(
                select(func.max(email_verifications.c.created_at)).where(
                    email_verifications.c.user_id == user_id
                )
            ).scalar_one_or_none()
        # SQLite returns naive datetimes; we always store UTC.
        return value.replace(tzinfo=UTC) if value is not None and value.tzinfo is None else value

    def consume(self, token_hash: str, now: datetime) -> EmailToken | None:
        # One UPDATE ... WHERE unused AND unexpired: two concurrent clicks cannot both win.
        with self._engine.begin() as conn:
            claimed = conn.execute(
                update(email_verifications)
                .where(
                    email_verifications.c.token_hash == token_hash,
                    email_verifications.c.used_at.is_(None),
                    email_verifications.c.expires_at > now,
                )
                .values(used_at=now)
            )
            if claimed.rowcount != 1:
                return None
            row = conn.execute(
                select(email_verifications.c.user_id, email_verifications.c.email).where(
                    email_verifications.c.token_hash == token_hash
                )
            ).one()
        return EmailToken(UserId(row.user_id), Email(row.email))


def _utc(value: datetime) -> datetime:
    """SQLite hands back naive datetimes; everything we store is UTC."""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


class SqlTenancyRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    # -- organizations -------------------------------------------------------------

    def add_org(self, org: Organization, owner: UserId) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                insert(organizations).values(id=org.id, name=org.name, preset_key=org.preset_key)
            )
            conn.execute(
                insert(org_memberships).values(
                    org_id=org.id, user_id=owner, role=OrgRole.OWNER.value
                )
            )

    def get_org(self, org_id: OrgId) -> Organization | None:
        with self._engine.connect() as conn:
            row = conn.execute(select(organizations).where(organizations.c.id == org_id)).first()
        return Organization(OrgId(row.id), row.name, row.preset_key) if row else None

    def org_role(self, org_id: OrgId, user_id: UserId) -> OrgRole | None:
        with self._engine.connect() as conn:
            role = conn.execute(
                select(org_memberships.c.role).where(
                    org_memberships.c.org_id == org_id, org_memberships.c.user_id == user_id
                )
            ).scalar_one_or_none()
        return OrgRole(role) if role else None

    def add_org_member(self, org_id: OrgId, user_id: UserId, role: OrgRole) -> None:
        if self.org_role(org_id, user_id) is not None:
            return
        try:
            with self._engine.begin() as conn:
                conn.execute(
                    insert(org_memberships).values(org_id=org_id, user_id=user_id, role=role.value)
                )
        except IntegrityError:
            pass  # lost a race with an identical insert: the membership exists

    def orgs_for_user(self, user_id: UserId) -> list[tuple[Organization, OrgRole]]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                select(organizations, org_memberships.c.role)
                .join(org_memberships, org_memberships.c.org_id == organizations.c.id)
                .where(org_memberships.c.user_id == user_id)
                .order_by(func.lower(organizations.c.name))
            ).all()
        return [(Organization(OrgId(r.id), r.name, r.preset_key), OrgRole(r.role)) for r in rows]

    # -- spaces --------------------------------------------------------------------

    def add_space(self, space: Space, creator: SpaceMember) -> None:
        with self._engine.begin() as conn:
            conn.execute(insert(spaces).values(id=space.id, org_id=space.org_id, name=space.name))
            conn.execute(insert(space_members).values(**_member_values(creator)))

    def get_space(self, space_id: SpaceId) -> Space | None:
        with self._engine.connect() as conn:
            row = conn.execute(select(spaces).where(spaces.c.id == space_id)).first()
        return Space(SpaceId(row.id), OrgId(row.org_id), row.name) if row else None

    def _spaces(self, *where) -> list[Space]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                select(spaces).where(*where).order_by(func.lower(spaces.c.name))
            ).all()
        return [Space(SpaceId(r.id), OrgId(r.org_id), r.name) for r in rows]

    def spaces_in_org(self, org_id: OrgId) -> list[Space]:
        return self._spaces(spaces.c.org_id == org_id)

    def spaces_of_member(self, org_id: OrgId, user_id: UserId) -> list[Space]:
        return self._spaces(
            spaces.c.org_id == org_id,
            spaces.c.id.in_(
                select(space_members.c.space_id).where(space_members.c.user_id == user_id)
            ),
        )

    def spaces_for_user(self, user_id: UserId) -> list[Space]:
        return self._spaces(
            spaces.c.id.in_(
                select(space_members.c.space_id).where(space_members.c.user_id == user_id)
            )
        )

    def space_member(self, space_id: SpaceId, user_id: UserId) -> SpaceMember | None:
        with self._engine.connect() as conn:
            row = conn.execute(
                select(space_members).where(
                    space_members.c.space_id == space_id, space_members.c.user_id == user_id
                )
            ).first()
        return _to_member(row) if row else None

    def space_members(self, space_id: SpaceId) -> list[SpaceMember]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                select(space_members).where(space_members.c.space_id == space_id)
            ).all()
        return [_to_member(r) for r in rows]

    def add_space_member(self, member: SpaceMember) -> None:
        if self.space_member(member.space_id, member.user_id) is not None:
            return
        try:
            with self._engine.begin() as conn:
                conn.execute(insert(space_members).values(**_member_values(member)))
        except IntegrityError:
            pass

    def set_space_member_role(self, space_id: SpaceId, user_id: UserId, role_key: str) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                update(space_members)
                .where(space_members.c.space_id == space_id, space_members.c.user_id == user_id)
                .values(role_key=role_key)
            )

    def remove_space_member(self, space_id: SpaceId, user_id: UserId) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                delete(group_members).where(
                    group_members.c.user_id == user_id,
                    group_members.c.group_id.in_(
                        select(groups.c.id).where(groups.c.space_id == space_id)
                    ),
                )
            )
            conn.execute(
                delete(space_members).where(
                    space_members.c.space_id == space_id, space_members.c.user_id == user_id
                )
            )

    # -- groups --------------------------------------------------------------------

    def add_group(self, group: Group) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                insert(groups).values(
                    id=group.id, org_id=group.org_id, space_id=group.space_id, name=group.name
                )
            )
            for user_id in group.members:
                conn.execute(
                    insert(group_members).values(
                        group_id=group.id, user_id=user_id, org_id=group.org_id
                    )
                )

    def _groups(self, where) -> list[Group]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                select(groups).where(where).order_by(func.lower(groups.c.name))
            ).all()
            ids = [r.id for r in rows]
            members: dict[str, set[UserId]] = {i: set() for i in ids}
            if ids:
                for gm in conn.execute(
                    select(group_members.c.group_id, group_members.c.user_id).where(
                        group_members.c.group_id.in_(ids)
                    )
                ):
                    members[gm.group_id].add(UserId(gm.user_id))
        return [
            Group(
                GroupId(r.id),
                OrgId(r.org_id),
                SpaceId(r.space_id),
                r.name,
                frozenset(members[r.id]),
            )
            for r in rows
        ]

    def get_group(self, group_id: GroupId) -> Group | None:
        found = self._groups(groups.c.id == group_id)
        return found[0] if found else None

    def groups_in_space(self, space_id: SpaceId) -> list[Group]:
        return self._groups(groups.c.space_id == space_id)

    def rename_group(self, group_id: GroupId, name: str) -> None:
        with self._engine.begin() as conn:
            conn.execute(update(groups).where(groups.c.id == group_id).values(name=name))

    def delete_group(self, group_id: GroupId) -> None:
        with self._engine.begin() as conn:
            conn.execute(delete(group_members).where(group_members.c.group_id == group_id))
            conn.execute(delete(groups).where(groups.c.id == group_id))

    def add_group_member(self, group_id: GroupId, user_id: UserId) -> None:
        group = self.get_group(group_id)
        if group is None or user_id in group.members:
            return
        try:
            with self._engine.begin() as conn:
                conn.execute(
                    insert(group_members).values(
                        group_id=group_id, user_id=user_id, org_id=group.org_id
                    )
                )
        except IntegrityError:
            pass

    def remove_group_member(self, group_id: GroupId, user_id: UserId) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                delete(group_members).where(
                    group_members.c.group_id == group_id, group_members.c.user_id == user_id
                )
            )

    # -- invites -------------------------------------------------------------------

    def add_invite(self, invite: Invite) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                insert(invites).values(
                    id=invite.id,
                    org_id=invite.org_id,
                    space_id=invite.space_id,
                    role_key=invite.role_key,
                    created_by=invite.created_by,
                    expires_at=invite.expires_at,
                    max_uses=invite.max_uses,
                    uses=invite.uses,
                    revoked=invite.revoked,
                )
            )

    @staticmethod
    def _invite(row: Row) -> Invite:
        return Invite(
            id=row.id,
            org_id=OrgId(row.org_id),
            space_id=SpaceId(row.space_id),
            role_key=row.role_key,
            created_by=UserId(row.created_by),
            expires_at=_utc(row.expires_at),
            max_uses=row.max_uses,
            uses=row.uses,
            revoked=bool(row.revoked),
        )

    def get_invite(self, invite_id: str) -> Invite | None:
        with self._engine.connect() as conn:
            row = conn.execute(select(invites).where(invites.c.id == invite_id)).first()
        return self._invite(row) if row else None

    def invites_in_space(self, space_id: SpaceId) -> list[Invite]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                select(invites).where(invites.c.space_id == space_id).order_by(invites.c.expires_at)
            ).all()
        return [self._invite(r) for r in rows]

    def revoke_invite(self, invite_id: str) -> None:
        with self._engine.begin() as conn:
            conn.execute(update(invites).where(invites.c.id == invite_id).values(revoked=True))

    def use_invite(self, invite_id: str, now: datetime) -> bool:
        # One conditional UPDATE: concurrent joins cannot exceed max_uses.
        with self._engine.begin() as conn:
            result = conn.execute(
                update(invites)
                .where(
                    invites.c.id == invite_id,
                    invites.c.revoked.is_(False),
                    invites.c.expires_at > now,
                    or_(invites.c.max_uses.is_(None), invites.c.uses < invites.c.max_uses),
                )
                .values(uses=invites.c.uses + 1)
            )
            return result.rowcount == 1


def _member_values(member: SpaceMember) -> dict[str, str]:
    return {
        "space_id": member.space_id,
        "org_id": member.org_id,
        "user_id": member.user_id,
        "role_key": member.role_key,
    }


def _to_member(row: Row) -> SpaceMember:
    return SpaceMember(OrgId(row.org_id), SpaceId(row.space_id), UserId(row.user_id), row.role_key)
