"""calls, submissions, revisions and share links

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def _space_fk() -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["space_id", "org_id"], ["spaces.id", "spaces.org_id"], ondelete="CASCADE"
    )


def _user_fk() -> sa.ForeignKey:
    return sa.ForeignKey("users.id", ondelete="CASCADE")


def upgrade() -> None:
    op.create_table(
        "calls",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("org_id", sa.String(64), nullable=False),
        sa.Column("space_id", sa.String(64), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.String(5000), nullable=False),
        sa.Column("artifact_type", sa.String(64), nullable=False),
        sa.Column("group_work", sa.Boolean, nullable=False),
        sa.Column("closes_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published", sa.Boolean, nullable=False),
        sa.Column("created_by", sa.String(64), _user_fk(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        _space_fk(),
        sa.UniqueConstraint("id", "org_id", name="uq_calls_id_org"),
    )
    op.create_index("ix_calls_space_id", "calls", ["space_id"])
    op.create_table(
        "submissions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("org_id", sa.String(64), nullable=False),
        sa.Column("space_id", sa.String(64), nullable=False),
        sa.Column("call_id", sa.String(64), nullable=False),
        sa.Column("author_kind", sa.String(16), nullable=False),
        sa.Column("author_id", sa.String(64), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["call_id", "org_id"], ["calls.id", "calls.org_id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint("id", "org_id", name="uq_submissions_id_org"),
        sa.UniqueConstraint("call_id", "author_kind", "author_id", name="uq_submissions_author"),
    )
    op.create_index("ix_submissions_call_id", "submissions", ["call_id"])
    op.create_table(
        "revisions",
        sa.Column("submission_id", sa.String(64), primary_key=True),
        sa.Column("number", sa.Integer, primary_key=True),
        sa.Column("org_id", sa.String(64), nullable=False),
        sa.Column("type_key", sa.String(64), nullable=False),
        sa.Column("media_type", sa.String(100), nullable=False),
        sa.Column("filename", sa.String(200), nullable=True),
        sa.Column("size", sa.Integer, nullable=False),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("content", sa.LargeBinary, nullable=False),
        sa.Column("created_by", sa.String(64), _user_fk(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["submission_id", "org_id"],
            ["submissions.id", "submissions.org_id"],
            ondelete="CASCADE",
        ),
    )
    op.create_table(
        "share_links",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("org_id", sa.String(64), nullable=False),
        sa.Column("space_id", sa.String(64), nullable=False),
        sa.Column("target", sa.String(16), nullable=False),
        sa.Column("target_id", sa.String(64), nullable=False),
        sa.Column("created_by", sa.String(64), _user_fk(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked", sa.Boolean, nullable=False),
        _space_fk(),
    )
    op.create_index("ix_share_links_target", "share_links", ["target", "target_id"])
    op.create_index("ix_share_links_created_by", "share_links", ["created_by"])
    op.create_table(
        "share_grants",
        sa.Column("user_id", sa.String(64), _user_fk(), primary_key=True),
        sa.Column("target", sa.String(16), primary_key=True),
        sa.Column("target_id", sa.String(64), primary_key=True),
        sa.Column("org_id", sa.String(64), nullable=False),
        sa.Column("space_id", sa.String(64), nullable=False),
        _space_fk(),
    )


def downgrade() -> None:
    for table in ("share_grants", "share_links", "revisions", "submissions", "calls"):
        op.drop_table(table)
