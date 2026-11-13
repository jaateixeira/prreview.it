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
    Column("roles", String(64), nullable=False),
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
    Column("roles", String(64), nullable=False),
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

rubrics = Table(
    "rubrics",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("org_id", String(64), nullable=False),
    Column("space_id", String(64), nullable=False),
    Column("name", String(100), nullable=False),
    Column("description", String(5000), nullable=False, default=""),
    Column("created_by", String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    ForeignKeyConstraint(
        ["space_id", "org_id"], ["spaces.id", "spaces.org_id"], ondelete="CASCADE"
    ),
    UniqueConstraint("id", "org_id", name="uq_rubrics_id_org"),
    Index("ix_rubrics_space_id", "space_id"),
)

criteria = Table(
    "criteria",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("org_id", String(64), nullable=False),
    Column("rubric_id", String(64), nullable=False),
    Column("position", Integer, nullable=False),
    Column("title", String(200), nullable=False),
    Column("guidance", String(1000), nullable=False, default=""),
    Column("type_key", String(64), nullable=False),
    Column("config", String(4000), nullable=False),  # JSON, normalised by the criterion type
    Column("weight", Integer, nullable=False),
    Column("required", Boolean, nullable=False),
    ForeignKeyConstraint(
        ["rubric_id", "org_id"], ["rubrics.id", "rubrics.org_id"], ondelete="CASCADE"
    ),
    Index("ix_criteria_rubric_id", "rubric_id"),
)

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
    # Nullable: a call without a rubric. A rubric in use cannot be deleted (no ON DELETE).
    Column("rubric_id", String(64), nullable=True),
    ForeignKeyConstraint(
        ["space_id", "org_id"], ["spaces.id", "spaces.org_id"], ondelete="CASCADE"
    ),
    ForeignKeyConstraint(["rubric_id", "org_id"], ["rubrics.id", "rubrics.org_id"]),
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


# --- review rounds and tasks ------------------------------------------------------------------

review_rounds = Table(
    "review_rounds",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("org_id", String(64), nullable=False),
    Column("space_id", String(64), nullable=False),
    Column("call_id", String(64), nullable=False),
    Column("number", Integer, nullable=False),
    Column("per_submission", Integer, nullable=False),
    Column("strategy_key", String(64), nullable=False),
    Column("anonymity_key", String(64), nullable=False),
    Column("opens_at", DateTime(timezone=True), nullable=True),
    Column("closes_at", DateTime(timezone=True), nullable=True),
    ForeignKeyConstraint(["call_id", "org_id"], ["calls.id", "calls.org_id"], ondelete="CASCADE"),
    UniqueConstraint("id", "org_id", name="uq_review_rounds_id_org"),
    UniqueConstraint("call_id", "number", name="uq_review_rounds_number"),
    Index("ix_review_rounds_call_id", "call_id"),
)

review_tasks = Table(
    "review_tasks",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("org_id", String(64), nullable=False),
    Column("space_id", String(64), nullable=False),
    Column("round_id", String(64), nullable=False),
    Column("reviewer_kind", String(16), nullable=False),  # user | group
    Column("reviewer_id", String(64), nullable=False),
    Column("submission_id", String(64), nullable=False),
    Column("revision_number", Integer, nullable=False),
    Column("manual", Boolean, nullable=False),
    ForeignKeyConstraint(
        ["round_id", "org_id"], ["review_rounds.id", "review_rounds.org_id"], ondelete="CASCADE"
    ),
    ForeignKeyConstraint(
        ["submission_id", "org_id"], ["submissions.id", "submissions.org_id"], ondelete="CASCADE"
    ),
    UniqueConstraint(
        "round_id", "reviewer_kind", "reviewer_id", "submission_id", name="uq_review_tasks_pair"
    ),
    UniqueConstraint("id", "org_id", name="uq_review_tasks_id_org"),
    Index("ix_review_tasks_round_id", "round_id"),
    Index("ix_review_tasks_reviewer", "space_id", "reviewer_kind", "reviewer_id"),
)


# --- reviews, their edit trail and annotations ------------------------------------------------

reviews = Table(
    "reviews",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("org_id", String(64), nullable=False),
    Column("space_id", String(64), nullable=False),
    Column("round_id", String(64), nullable=False),
    Column("task_id", String(64), nullable=False),
    Column("answers", String(60000), nullable=False),  # JSON: criterion id -> answer
    Column("version", Integer, nullable=False),
    Column("submitted", Boolean, nullable=False),
    Column("updated_by", String(64), nullable=True),
    Column("updated_at", DateTime(timezone=True), nullable=True),
    ForeignKeyConstraint(
        ["task_id", "org_id"], ["review_tasks.id", "review_tasks.org_id"], ondelete="CASCADE"
    ),
    UniqueConstraint("id", "org_id", name="uq_reviews_id_org"),
    UniqueConstraint("task_id", name="uq_reviews_task"),  # one review per task
    Index("ix_reviews_round_id", "round_id"),
)

review_edits = Table(
    "review_edits",
    metadata,
    Column("review_id", String(64), primary_key=True),
    Column("version", Integer, primary_key=True),
    Column("org_id", String(64), nullable=False),
    Column("user_id", String(64), nullable=False),
    Column("at", DateTime(timezone=True), nullable=False),
    ForeignKeyConstraint(
        ["review_id", "org_id"], ["reviews.id", "reviews.org_id"], ondelete="CASCADE"
    ),
)

annotations = Table(
    "annotations",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("org_id", String(64), nullable=False),
    Column("space_id", String(64), nullable=False),
    Column("review_id", String(64), nullable=False),
    Column("revision_number", Integer, nullable=False),
    Column("kind", String(32), nullable=False),
    Column("selector", String(2000), nullable=False),  # JSON, normalised by the artifact type
    Column("body", String(2000), nullable=False),
    Column("created_by", String(64), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    ForeignKeyConstraint(
        ["review_id", "org_id"], ["reviews.id", "reviews.org_id"], ondelete="CASCADE"
    ),
    Index("ix_annotations_review_id", "review_id"),
)
