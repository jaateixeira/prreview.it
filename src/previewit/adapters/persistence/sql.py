"""SQL implementation of the user repository (SQLAlchemy Core; SQLite and PostgreSQL)."""

from __future__ import annotations

from sqlalchemy import Engine, and_, insert, select, update
from sqlalchemy.engine import Connection, Row
from sqlalchemy.exc import IntegrityError

from previewit.adapters.persistence.tables import external_identities, users
from previewit.application.ports import DuplicateEmail, DuplicateIdentity
from previewit.domain.identity import Email, IdentityKey, Provider, User, UserId


class SqlUserRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    # -- reads ---------------------------------------------------------------

    def get(self, user_id: UserId) -> User | None:
        with self._engine.connect() as conn:
            return self._load(conn, users.c.id == user_id)

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
