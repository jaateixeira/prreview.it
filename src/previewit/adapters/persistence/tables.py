"""SQLAlchemy Core table definitions. The Alembic migrations must match these."""

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    MetaData,
    String,
    Table,
    UniqueConstraint,
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


# --- tenancy: every row below carries org_id -------------------------------------------------
# Composite foreign keys (space_id, org_id) make it impossible for a child row to name a
# different tenant than its parent.

organizations = Table(
    "organizations",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("name", String(100), nullable=False),
    Column("preset_key", String(64), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

org_memberships = Table(
    "org_memberships",
    metadata,
    Column(
        "org_id", String(64), ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    ),
    Column("user_id", String(64), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("role", String(32), nullable=False),
    Index("ix_org_memberships_user_id", "user_id"),
)

spaces = Table(
    "spaces",
    metadata,
    Column("id", String(64), primary_key=True),
    Column(
        "org_id", String(64), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    ),
    Column("name", String(100), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("id", "org_id", name="uq_spaces_id_org"),
    Index("ix_spaces_org_id", "org_id"),
)

space_members = Table(
    "space_members",
    metadata,
    Column("space_id", String(64), primary_key=True),
    Column("user_id", String(64), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("org_id", String(64), nullable=False),
    Column("role_key", String(64), nullable=False),
    ForeignKeyConstraint(
        ["space_id", "org_id"], ["spaces.id", "spaces.org_id"], ondelete="CASCADE"
    ),
    Index("ix_space_members_user_id", "user_id"),
)

groups = Table(
    "groups",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("org_id", String(64), nullable=False),
    Column("space_id", String(64), nullable=False),
    Column("name", String(100), nullable=False),
    ForeignKeyConstraint(
        ["space_id", "org_id"], ["spaces.id", "spaces.org_id"], ondelete="CASCADE"
    ),
    UniqueConstraint("id", "org_id", name="uq_groups_id_org"),
    Index("ix_groups_space_id", "space_id"),
)

group_members = Table(
    "group_members",
    metadata,
    Column("group_id", String(64), primary_key=True),
    Column("user_id", String(64), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("org_id", String(64), nullable=False),
    ForeignKeyConstraint(
        ["group_id", "org_id"], ["groups.id", "groups.org_id"], ondelete="CASCADE"
    ),
)

invites = Table(
    "invites",
    metadata,
    Column("id", String(64), primary_key=True),  # SHA-256 of the secret in the link
    Column("org_id", String(64), nullable=False),
    Column("space_id", String(64), nullable=False),
    Column("role_key", String(64), nullable=False),
    Column("created_by", String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("max_uses", Integer, nullable=True),
    Column("uses", Integer, nullable=False, default=0),
    Column("revoked", Boolean, nullable=False, default=False),
    ForeignKeyConstraint(
        ["space_id", "org_id"], ["spaces.id", "spaces.org_id"], ondelete="CASCADE"
    ),
    Index("ix_invites_space_id", "space_id"),
)


# --- calls, submissions, revisions, sharing (all carry org_id) -------------------------------

calls = Table(
    "calls",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("org_id", String(64), nullable=False),
    Column("space_id", String(64), nullable=False),
    Column("title", String(200), nullable=False),
    Column("description", String(5000), nullable=False, default=""),
    Column("artifact_type", String(64), nullable=False),
    Column("group_work", Boolean, nullable=False, default=False),
    Column("closes_at", DateTime(timezone=True), nullable=True),
    Column("published", Boolean, nullable=False, default=False),
    Column("created_by", String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    ForeignKeyConstraint(
        ["space_id", "org_id"], ["spaces.id", "spaces.org_id"], ondelete="CASCADE"
    ),
    UniqueConstraint("id", "org_id", name="uq_calls_id_org"),
    Index("ix_calls_space_id", "space_id"),
)

submissions = Table(
    "submissions",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("org_id", String(64), nullable=False),
    Column("space_id", String(64), nullable=False),
    Column("call_id", String(64), nullable=False),
    Column("author_kind", String(16), nullable=False),  # user | group
    Column("author_id", String(64), nullable=False),
    Column("title", String(200), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    ForeignKeyConstraint(["call_id", "org_id"], ["calls.id", "calls.org_id"], ondelete="CASCADE"),
    UniqueConstraint("id", "org_id", name="uq_submissions_id_org"),
    # one submission per author per call
    UniqueConstraint("call_id", "author_kind", "author_id", name="uq_submissions_author"),
    Index("ix_submissions_call_id", "call_id"),
)

revisions = Table(
    "revisions",
    metadata,
    Column("submission_id", String(64), primary_key=True),
    Column("number", Integer, primary_key=True),
    Column("org_id", String(64), nullable=False),
    Column("type_key", String(64), nullable=False),
    Column("media_type", String(100), nullable=False),
    Column("filename", String(200), nullable=True),
    Column("size", Integer, nullable=False),
    Column("digest", String(64), nullable=False),
    Column("content", LargeBinary, nullable=False),
    Column("created_by", String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    ForeignKeyConstraint(
        ["submission_id", "org_id"], ["submissions.id", "submissions.org_id"], ondelete="CASCADE"
    ),
)

share_links = Table(
    "share_links",
    metadata,
    Column("id", String(64), primary_key=True),  # SHA-256 of the secret in the link
    Column("org_id", String(64), nullable=False),
    Column("space_id", String(64), nullable=False),
    Column("target", String(16), nullable=False),  # call | submission
    Column("target_id", String(64), nullable=False),
    Column("created_by", String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("revoked", Boolean, nullable=False, default=False),
    ForeignKeyConstraint(
        ["space_id", "org_id"], ["spaces.id", "spaces.org_id"], ondelete="CASCADE"
    ),
    Index("ix_share_links_target", "target", "target_id"),
    Index("ix_share_links_created_by", "created_by"),
)

share_grants = Table(
    "share_grants",
    metadata,
    Column("user_id", String(64), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("target", String(16), primary_key=True),
    Column("target_id", String(64), primary_key=True),
    Column("org_id", String(64), nullable=False),
    Column("space_id", String(64), nullable=False),
    ForeignKeyConstraint(
        ["space_id", "org_id"], ["spaces.id", "spaces.org_id"], ondelete="CASCADE"
    ),
)
