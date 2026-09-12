"""Per-scan usage and cost, content-free scan traces, database rate limits,
and an 'active' flag so reading the plan no longer rebuilds it.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-11
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

_COUNTERS = ("model_calls", "tool_calls", "input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens")
_EVENT_TOKENS = ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens")


def upgrade() -> None:
    with op.batch_alter_table("scans") as batch:
        for column in _COUNTERS:
            batch.add_column(sa.Column(column, sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("duration_ms", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("cost_usd", sa.Float(), nullable=True))

    with op.batch_alter_table("remediation_items") as batch:
        batch.add_column(sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()))

    op.create_table(
        "scan_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("scan_id", sa.String(36), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("detail", sa.String(64), nullable=True),
        sa.Column("offset_ms", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        *(sa.Column(c, sa.Integer(), nullable=False, server_default="0") for c in _EVENT_TOKENS),
        sa.PrimaryKeyConstraint("id", name="pk_scan_events"),
        sa.ForeignKeyConstraint(["scan_id"], ["scans.id"], name="fk_scan_events_scan_id_scans", ondelete="CASCADE"),
    )
    op.create_index("ix_scan_events_scan_id", "scan_events", ["scan_id"])

    op.create_table(
        "rate_limit_windows",
        sa.Column("key", sa.String(200), nullable=False),
        sa.Column("window_start", sa.BigInteger(), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("key", "window_start", name="pk_rate_limit_windows"),
    )


def downgrade() -> None:
    op.drop_table("rate_limit_windows")
    op.drop_index("ix_scan_events_scan_id", table_name="scan_events")
    op.drop_table("scan_events")
    with op.batch_alter_table("remediation_items") as batch:
        batch.drop_column("active")
    with op.batch_alter_table("scans") as batch:
        for column in (*_COUNTERS, "duration_ms", "cost_usd"):
            batch.drop_column(column)
