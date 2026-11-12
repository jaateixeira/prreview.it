"""review rounds and review tasks

Revision ID: 0006
Revises: 0005
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "review_rounds",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("org_id", sa.String(64), nullable=False),
        sa.Column("space_id", sa.String(64), nullable=False),
        sa.Column("call_id", sa.String(64), nullable=False),
        sa.Column("number", sa.Integer, nullable=False),
        sa.Column("per_submission", sa.Integer, nullable=False),
        sa.Column("strategy_key", sa.String(64), nullable=False),
        sa.Column("anonymity_key", sa.String(64), nullable=False),
        sa.Column("opens_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closes_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["call_id", "org_id"], ["calls.id", "calls.org_id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint("id", "org_id", name="uq_review_rounds_id_org"),
        sa.UniqueConstraint("call_id", "number", name="uq_review_rounds_number"),
    )
    op.create_index("ix_review_rounds_call_id", "review_rounds", ["call_id"])
    op.create_table(
        "review_tasks",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("org_id", sa.String(64), nullable=False),
        sa.Column("space_id", sa.String(64), nullable=False),
        sa.Column("round_id", sa.String(64), nullable=False),
        sa.Column("reviewer_kind", sa.String(16), nullable=False),
        sa.Column("reviewer_id", sa.String(64), nullable=False),
        sa.Column("submission_id", sa.String(64), nullable=False),
        sa.Column("revision_number", sa.Integer, nullable=False),
        sa.Column("manual", sa.Boolean, nullable=False),
        sa.ForeignKeyConstraint(
            ["round_id", "org_id"], ["review_rounds.id", "review_rounds.org_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["submission_id", "org_id"],
            ["submissions.id", "submissions.org_id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "round_id", "reviewer_kind", "reviewer_id", "submission_id", name="uq_review_tasks_pair"
        ),
    )
    op.create_index("ix_review_tasks_round_id", "review_tasks", ["round_id"])
    op.create_index(
        "ix_review_tasks_reviewer", "review_tasks", ["space_id", "reviewer_kind", "reviewer_id"]
    )


def downgrade() -> None:
    op.drop_table("review_tasks")
    op.drop_table("review_rounds")
