"""Initial schema: everything up to and including username proofs.

Databases created before migrations existed (create_all plus hand-applied
ALTERs) match this revision; mark them with `exposure-auditor migrate --stamp 0001`.

Revision ID: 0001
Revises:
Create Date: 2026-09-11
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def _ts(name: str, nullable: bool = False) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def _fk(table: str, column: str, target: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        [column], [f"{target}.id"], name=f"fk_{table}_{column}_{target}", ondelete="CASCADE"
    )


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("email_index", sa.String(64), nullable=False),
        sa.Column("email", sa.LargeBinary(), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        _ts("created_at"),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("email_index", name="uq_users_email_index"),
    )

    op.create_table(
        "identifiers",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("value", sa.LargeBinary(), nullable=False),
        sa.Column("value_index", sa.String(64), nullable=False),
        sa.Column("image_data", sa.LargeBinary(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("code_hash", sa.String(64), nullable=True),
        _ts("code_expires_at", nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        _ts("created_at"),
        _ts("verified_at", nullable=True),
        sa.Column("proof_platform", sa.String(16), nullable=True),
        sa.Column("proof_code", sa.String(40), nullable=True),
        _ts("proof_expires_at", nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_identifiers"),
        _fk("identifiers", "user_id", "users"),
        sa.UniqueConstraint("user_id", "value_index", name="uq_identifiers_user_id_value_index"),
    )
    op.create_index("ix_identifiers_user_id", "identifiers", ["user_id"])

    op.create_table(
        "scans",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("summary", sa.LargeBinary(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        _ts("created_at"),
        _ts("started_at", nullable=True),
        _ts("finished_at", nullable=True),
        sa.Column("namesakes_excluded", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("id", name="pk_scans"),
        _fk("scans", "user_id", "users"),
    )
    op.create_index("ix_scans_user_id", "scans", ["user_id"])

    op.create_table(
        "findings",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("scan_id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("url", sa.LargeBinary(), nullable=False),
        sa.Column("title", sa.LargeBinary(), nullable=False),
        sa.Column("broker_id", sa.String(64), nullable=True),
        sa.Column("matched_identifier_ids", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.String(8), nullable=False),
        sa.Column("rationale", sa.LargeBinary(), nullable=False),
        sa.Column("match_status", sa.String(16), nullable=False, server_default="likely"),
        _ts("created_at"),
        sa.PrimaryKeyConstraint("id", name="pk_findings"),
        _fk("findings", "scan_id", "scans"),
        _fk("findings", "user_id", "users"),
    )
    op.create_index("ix_findings_scan_id", "findings", ["scan_id"])
    op.create_index("ix_findings_user_id", "findings", ["user_id"])

    op.create_table(
        "finding_suppressions",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("url_index", sa.String(64), nullable=False),
        _ts("created_at"),
        sa.PrimaryKeyConstraint("id", name="pk_finding_suppressions"),
        _fk("finding_suppressions", "user_id", "users"),
        sa.UniqueConstraint("user_id", "url_index", name="uq_finding_suppressions_user_id_url_index"),
    )
    op.create_index("ix_finding_suppressions_user_id", "finding_suppressions", ["user_id"])

    op.create_table(
        "breach_hits",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("identifier_id", sa.String(36), nullable=False),
        sa.Column("breach_name", sa.String(128), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("domain", sa.String(255), nullable=False),
        sa.Column("breach_date", sa.String(16), nullable=False),
        sa.Column("data_classes", sa.JSON(), nullable=False),
        sa.Column("is_verified", sa.Boolean(), nullable=False),
        _ts("checked_at"),
        sa.PrimaryKeyConstraint("id", name="pk_breach_hits"),
        _fk("breach_hits", "user_id", "users"),
        _fk("breach_hits", "identifier_id", "identifiers"),
        sa.UniqueConstraint("identifier_id", "breach_name", name="uq_breach_hits_identifier_id_breach_name"),
    )
    op.create_index("ix_breach_hits_user_id", "breach_hits", ["user_id"])

    op.create_table(
        "remediation_items",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("dedupe_key", sa.String(255), nullable=False),
        sa.Column("source_type", sa.String(16), nullable=False),
        sa.Column("source_id", sa.String(36), nullable=True),
        sa.Column("action_type", sa.String(32), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("title", sa.LargeBinary(), nullable=False),
        sa.Column("detail", sa.LargeBinary(), nullable=False),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("draft", sa.LargeBinary(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        _ts("created_at"),
        _ts("updated_at"),
        sa.PrimaryKeyConstraint("id", name="pk_remediation_items"),
        _fk("remediation_items", "user_id", "users"),
        sa.UniqueConstraint("user_id", "dedupe_key", name="uq_remediation_items_user_id_dedupe_key"),
    )
    op.create_index("ix_remediation_items_user_id", "remediation_items", ["user_id"])

    op.create_table(
        "audit_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.String(36), nullable=True),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("target_type", sa.String(32), nullable=True),
        sa.Column("target_id", sa.String(36), nullable=True),
        _ts("at"),
        sa.PrimaryKeyConstraint("id", name="pk_audit_events"),
    )
    op.create_index("ix_audit_events_user_id", "audit_events", ["user_id"])


def downgrade() -> None:
    for table in (
        "audit_events",
        "remediation_items",
        "breach_hits",
        "finding_suppressions",
        "findings",
        "scans",
        "identifiers",
        "users",
    ):
        op.drop_table(table)
