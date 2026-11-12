"""fixed roles: organizer, author, reviewer (ADR 0017)

space_members.role_key and invites.role_key become `roles`, a comma-separated set.
teacher and assistant become organizer; student becomes author and reviewer.

Revision ID: 0009
Revises: 0008
"""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

TABLES = ("space_members", "invites")
FORWARD = {"teacher": "organizer", "assistant": "organizer", "student": "author,reviewer"}
BACKWARD = {"organizer": "teacher", "author,reviewer": "student"}


def _rename(old: str, new: str, mapping: dict[str, str], default: str) -> None:
    for table in TABLES:
        with op.batch_alter_table(table) as batch:
            batch.alter_column(old, new_column_name=new, existing_type=sa.String(64))
        for before, after in mapping.items():
            op.execute(
                sa.text(f"UPDATE {table} SET {new} = :after WHERE {new} = :before").bindparams(
                    before=before, after=after
                )
            )
        # anything else (an unknown or custom role) gets the least-privileged valid value
        known = ", ".join(f"'{k}'" for k in mapping.values())
        op.execute(sa.text(f"UPDATE {table} SET {new} = '{default}' WHERE {new} NOT IN ({known})"))


def upgrade() -> None:
    _rename("role_key", "roles", FORWARD, "reviewer")


def downgrade() -> None:
    _rename("roles", "role_key", BACKWARD, "student")
