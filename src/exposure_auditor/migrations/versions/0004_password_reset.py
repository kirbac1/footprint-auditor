"""A password reset in progress: a keyed hash of the code, never the code.

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-12
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("reset_code_hash", sa.String(64), nullable=True))
        batch.add_column(sa.Column("reset_expires_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("reset_attempts", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_column("reset_attempts")
        batch.drop_column("reset_expires_at")
        batch.drop_column("reset_code_hash")
