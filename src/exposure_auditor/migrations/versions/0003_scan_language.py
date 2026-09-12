"""Scan language, so rationales and the summary can come back in Finnish.

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-11
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("scans") as batch:
        batch.add_column(sa.Column("language", sa.String(8), nullable=False, server_default="en"))


def downgrade() -> None:
    with op.batch_alter_table("scans") as batch:
        batch.drop_column("language")
