"""call access: public or protected (ADR 0017)

Existing calls become protected: only a link with a token admits new authors.

Revision ID: 0010
Revises: 0009
"""

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("calls") as batch:
        batch.add_column(
            sa.Column("access", sa.String(16), nullable=False, server_default="protected")
        )


def downgrade() -> None:
    with op.batch_alter_table("calls") as batch:
        batch.drop_column("access")
