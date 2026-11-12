"""organizations, spaces, memberships, groups and invites

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("preset_key", sa.String(64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_table(
        "org_memberships",
        sa.Column(
            "org_id",
            sa.String(64),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            sa.String(64),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("role", sa.String(32), nullable=False),
    )
    op.create_index("ix_org_memberships_user_id", "org_memberships", ["user_id"])
    op.create_table(
        "spaces",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "org_id",
            sa.String(64),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("id", "org_id", name="uq_spaces_id_org"),
    )
    op.create_index("ix_spaces_org_id", "spaces", ["org_id"])
    op.create_table(
        "space_members",
        sa.Column("space_id", sa.String(64), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(64),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("org_id", sa.String(64), nullable=False),
        sa.Column("role_key", sa.String(64), nullable=False),
        sa.ForeignKeyConstraint(
            ["space_id", "org_id"], ["spaces.id", "spaces.org_id"], ondelete="CASCADE"
        ),
    )
    op.create_index("ix_space_members_user_id", "space_members", ["user_id"])
    op.create_table(
        "groups",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("org_id", sa.String(64), nullable=False),
        sa.Column("space_id", sa.String(64), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.ForeignKeyConstraint(
            ["space_id", "org_id"], ["spaces.id", "spaces.org_id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint("id", "org_id", name="uq_groups_id_org"),
    )
    op.create_index("ix_groups_space_id", "groups", ["space_id"])
    op.create_table(
        "group_members",
        sa.Column("group_id", sa.String(64), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(64),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("org_id", sa.String(64), nullable=False),
        sa.ForeignKeyConstraint(
            ["group_id", "org_id"], ["groups.id", "groups.org_id"], ondelete="CASCADE"
        ),
    )
    op.create_table(
        "invites",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("org_id", sa.String(64), nullable=False),
        sa.Column("space_id", sa.String(64), nullable=False),
        sa.Column("role_key", sa.String(64), nullable=False),
        sa.Column(
            "created_by",
            sa.String(64),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("max_uses", sa.Integer, nullable=True),
        sa.Column("uses", sa.Integer, nullable=False),
        sa.Column("revoked", sa.Boolean, nullable=False),
        sa.ForeignKeyConstraint(
            ["space_id", "org_id"], ["spaces.id", "spaces.org_id"], ondelete="CASCADE"
        ),
    )
    op.create_index("ix_invites_space_id", "invites", ["space_id"])


def downgrade() -> None:
    for table in (
        "invites",
        "group_members",
        "groups",
        "space_members",
        "spaces",
        "org_memberships",
        "organizations",
    ):
        op.drop_table(table)
