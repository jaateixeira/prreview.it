"""rubrics, criteria, and a rubric on each call

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rubrics",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("org_id", sa.String(64), nullable=False),
        sa.Column("space_id", sa.String(64), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.String(5000), nullable=False),
        sa.Column(
            "created_by",
            sa.String(64),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(
            ["space_id", "org_id"], ["spaces.id", "spaces.org_id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint("id", "org_id", name="uq_rubrics_id_org"),
    )
    op.create_index("ix_rubrics_space_id", "rubrics", ["space_id"])
    op.create_table(
        "criteria",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("org_id", sa.String(64), nullable=False),
        sa.Column("rubric_id", sa.String(64), nullable=False),
        sa.Column("position", sa.Integer, nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("guidance", sa.String(1000), nullable=False),
        sa.Column("type_key", sa.String(64), nullable=False),
        sa.Column("config", sa.String(4000), nullable=False),
        sa.Column("weight", sa.Integer, nullable=False),
        sa.Column("required", sa.Boolean, nullable=False),
        sa.ForeignKeyConstraint(
            ["rubric_id", "org_id"], ["rubrics.id", "rubrics.org_id"], ondelete="CASCADE"
        ),
    )
    op.create_index("ix_criteria_rubric_id", "criteria", ["rubric_id"])
    with op.batch_alter_table("calls") as batch:
        batch.add_column(sa.Column("rubric_id", sa.String(64), nullable=True))
        batch.create_foreign_key(
            "fk_calls_rubric", "rubrics", ["rubric_id", "org_id"], ["id", "org_id"]
        )


def downgrade() -> None:
    with op.batch_alter_table("calls") as batch:
        batch.drop_constraint("fk_calls_rubric", type_="foreignkey")
        batch.drop_column("rubric_id")
    op.drop_table("criteria")
    op.drop_table("rubrics")
