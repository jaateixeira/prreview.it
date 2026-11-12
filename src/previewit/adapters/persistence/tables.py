"""SQLAlchemy Core table definitions. The Alembic migrations must match these."""

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    MetaData,
    String,
    Table,
    func,
)

metadata = MetaData()

users = Table(
    "users",
    metadata,
    Column("id", String(64), primary_key=True),
    # Stored lower-case (the domain normalises); NULL for users without a trusted email.
    Column("email", String(254), nullable=True),
    Column("email_verified", Boolean, nullable=False, default=False),
    Column("display_name", String(200), nullable=False),
    Column("password_hash", String(255), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Index("uq_users_email", "email", unique=True),
)

external_identities = Table(
    "external_identities",
    metadata,
    Column("provider", String(32), primary_key=True),
    Column("subject", String(512), primary_key=True),
    Column("user_id", String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Index("ix_external_identities_user_id", "user_id"),
)

email_verifications = Table(
    "email_verifications",
    metadata,
    Column("token_hash", String(64), primary_key=True),
    Column("user_id", String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("email", String(254), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("used_at", DateTime(timezone=True), nullable=True),
    Index("ix_email_verifications_user_id", "user_id"),
)
