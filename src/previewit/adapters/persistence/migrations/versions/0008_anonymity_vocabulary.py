"""rename the anonymity preset double_blind to double_anonymous (ADR 0016)

Revision ID: 0008
Revises: 0007
"""

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "UPDATE review_rounds SET anonymity_key = 'double_anonymous' "
        "WHERE anonymity_key = 'double_blind'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE review_rounds SET anonymity_key = 'double_blind' "
        "WHERE anonymity_key = 'double_anonymous'"
    )
