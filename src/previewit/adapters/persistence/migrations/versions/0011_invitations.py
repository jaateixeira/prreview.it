"""reviewer invitations (ADR 0017)

One personal invitation per reviewer: an email, a token (stored as its hash), a round and
the work the reviewer is asked to review.

Revision ID: 0011
Revises: 0010
"""

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "invitations",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("org_id", sa.String(64), nullable=False),
        sa.Column("space_id", sa.String(64), nullable=False),
        sa.Column("round_id", sa.String(64), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column(
            "created_by",
            sa.String(64),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked", sa.Boolean, nullable=False),
        sa.Column(
            "accepted_by",
            sa.String(64),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["round_id", "org_id"], ["review_rounds.id", "review_rounds.org_id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint("id", "org_id", name="uq_invitations_id_org"),
    )
    op.create_index("ix_invitations_round_id", "invitations", ["round_id"])
    op.create_index("ix_invitations_created_by", "invitations", ["created_by"])
    op.create_table(
        "invitation_submissions",
        sa.Column("invitation_id", sa.String(64), primary_key=True),
        sa.Column("submission_id", sa.String(64), primary_key=True),
        sa.Column("org_id", sa.String(64), nullable=False),
        sa.Column("position", sa.Integer, nullable=False),
        sa.ForeignKeyConstraint(
            ["invitation_id", "org_id"],
            ["invitations.id", "invitations.org_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["submission_id", "org_id"],
            ["submissions.id", "submissions.org_id"],
            ondelete="CASCADE",
        ),
    )


def downgrade() -> None:
    op.drop_table("invitation_submissions")
    op.drop_index("ix_invitations_created_by", table_name="invitations")
    op.drop_index("ix_invitations_round_id", table_name="invitations")
    op.drop_table("invitations")
