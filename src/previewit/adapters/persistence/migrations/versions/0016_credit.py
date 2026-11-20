"""credit bought through Paddle and spent on AI reviews (ADR 0026)

Revision ID: 0016
Revises: 0015
"""

import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "credit_entries",
        sa.Column("seq", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("id", sa.String(64), nullable=False, unique=True),
        sa.Column(
            "user_id",
            sa.String(64),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("reference", sa.String(100), nullable=False),
        sa.Column("related", sa.String(100), nullable=False, server_default=""),
        sa.Column("paid_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("kind", "reference", name="uq_credit_entries_kind_reference"),
    )
    op.create_index("ix_credit_entries_user_id", "credit_entries", ["user_id"])
    op.create_index("ix_credit_entries_related", "credit_entries", ["kind", "related"])
    with op.batch_alter_table("ai_reviews") as batch:
        batch.add_column(
            sa.Column("credit_cents", sa.Integer(), nullable=False, server_default="0")
        )


def downgrade() -> None:
    with op.batch_alter_table("ai_reviews") as batch:
        batch.drop_column("credit_cents")
    op.drop_table("credit_entries")
