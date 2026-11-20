"""AI reviews: written by a model, seen by the author and the organizers (ADR 0025)

Revision ID: 0015
Revises: 0014
"""

import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_reviews",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("org_id", sa.String(64), nullable=False),
        sa.Column("submission_id", sa.String(64), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("model_key", sa.String(200), nullable=False),
        sa.Column("model_name", sa.String(200), nullable=False),
        sa.Column("hosted_in", sa.String(8), nullable=False),
        sa.Column("hosting", sa.String(200), nullable=False),
        sa.Column("payer", sa.String(16), nullable=False),
        sa.Column("requested_by", sa.String(64), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("problem", sa.Text(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("cost_microusd", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["submission_id", "org_id"],
            ["submissions.id", "submissions.org_id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_ai_reviews_submission_id", "ai_reviews", ["submission_id"])
    op.create_index("ix_ai_reviews_requested_by", "ai_reviews", ["requested_by", "requested_at"])
    op.create_index("ix_ai_reviews_status", "ai_reviews", ["status"])


def downgrade() -> None:
    op.drop_table("ai_reviews")
