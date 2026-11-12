"""reviews, review edit trail and annotations

Revision ID: 0007
Revises: 0006
"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("review_tasks") as batch:
        batch.create_unique_constraint("uq_review_tasks_id_org", ["id", "org_id"])
    op.create_table(
        "reviews",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("org_id", sa.String(64), nullable=False),
        sa.Column("space_id", sa.String(64), nullable=False),
        sa.Column("round_id", sa.String(64), nullable=False),
        sa.Column("task_id", sa.String(64), nullable=False),
        sa.Column("answers", sa.String(60000), nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("submitted", sa.Boolean, nullable=False),
        sa.Column("updated_by", sa.String(64), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["task_id", "org_id"], ["review_tasks.id", "review_tasks.org_id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint("id", "org_id", name="uq_reviews_id_org"),
        sa.UniqueConstraint("task_id", name="uq_reviews_task"),
    )
    op.create_index("ix_reviews_round_id", "reviews", ["round_id"])
    op.create_table(
        "review_edits",
        sa.Column("review_id", sa.String(64), primary_key=True),
        sa.Column("version", sa.Integer, primary_key=True),
        sa.Column("org_id", sa.String(64), nullable=False),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["review_id", "org_id"], ["reviews.id", "reviews.org_id"], ondelete="CASCADE"
        ),
    )
    op.create_table(
        "annotations",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("org_id", sa.String(64), nullable=False),
        sa.Column("space_id", sa.String(64), nullable=False),
        sa.Column("review_id", sa.String(64), nullable=False),
        sa.Column("revision_number", sa.Integer, nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("selector", sa.String(2000), nullable=False),
        sa.Column("body", sa.String(2000), nullable=False),
        sa.Column("created_by", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["review_id", "org_id"], ["reviews.id", "reviews.org_id"], ondelete="CASCADE"
        ),
    )
    op.create_index("ix_annotations_review_id", "annotations", ["review_id"])


def downgrade() -> None:
    op.drop_table("annotations")
    op.drop_table("review_edits")
    op.drop_table("reviews")
    with op.batch_alter_table("review_tasks") as batch:
        batch.drop_constraint("uq_review_tasks_id_org", type_="unique")
