"""add compliance tables and campaign compliance fields

Revision ID: e1f2a3b4c5d6
Revises: d9e0f1a2b3c4
Create Date: 2026-06-11 00:00:00.000000

Phase A of telecom compliance: internal DNC/suppression list, consent records,
and an immutable audit log, plus per-campaign compliance configuration
(region, AI disclosure, consent requirement, DNC scrub). External registry
sync (FTC DNC, TPS/CTPS, STIR/SHAKEN) is Phase B and reuses these tables.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e1f2a3b4c5d6"
down_revision: Union[str, None] = "d9e0f1a2b3c4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(table: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_name = :table"
        ),
        {"table": table},
    )
    return result.scalar() is not None


def _column_exists(table: str, column: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = :table AND column_name = :column"
        ),
        {"table": table, "column": column},
    )
    return result.scalar() is not None


def upgrade() -> None:
    bind = op.get_bind()

    # create_type=False is critical: we create the enum types explicitly via
    # `enum.create(bind, checkfirst=True)` below. Without this, op.create_table /
    # op.add_column would auto-emit a second `CREATE TYPE` (no checkfirst),
    # which fails with DuplicateObjectError on any partially-applied DB.
    dnc_source = postgresql.ENUM(
        "internal",
        "opt_out_request",
        "ftc_dnc",
        "tps",
        "ctps",
        name="compliance_dnc_source",
        create_type=False,
    )
    consent_type = postgresql.ENUM(
        "express_written",
        "express_oral",
        "prior_relationship",
        "opt_in",
        name="compliance_consent_type",
        create_type=False,
    )
    regulation = postgresql.ENUM(
        "tcpa", "pecr", "uk_gdpr", name="compliance_regulation",
        create_type=False,
    )
    audit_action = postgresql.ENUM(
        "call_allowed",
        "call_blocked_dnc",
        "call_blocked_no_consent",
        "call_blocked_hours",
        "consent_recorded",
        "consent_revoked",
        "dnc_added",
        "dnc_removed",
        "ai_disclosure_played",
        "data_erased",
        name="compliance_audit_action",
        create_type=False,
    )
    audit_regulation = postgresql.ENUM(
        "tcpa", "pecr", "uk_gdpr", "dnc", "ofcom", "stir_shaken",
        name="compliance_audit_regulation",
        create_type=False,
    )
    campaign_region = postgresql.ENUM(
        "us", "gb", "both", name="campaign_compliance_region",
        create_type=False,
    )

    for enum in (
        dnc_source,
        consent_type,
        regulation,
        audit_action,
        audit_regulation,
        campaign_region,
    ):
        enum.create(bind, checkfirst=True)

    if not _table_exists("compliance_dnc_entries"):
        op.create_table(
            "compliance_dnc_entries",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("organization_id", sa.Integer(), nullable=False),
            sa.Column("phone_number_hash", sa.String(length=64), nullable=False),
            sa.Column("phone_number_e164", sa.String(length=20), nullable=False),
            sa.Column(
                "source",
                dnc_source,
                nullable=False,
                server_default="internal",
            ),
            sa.Column("country_code", sa.String(length=2), nullable=True),
            sa.Column(
                "is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")
            ),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("added_by", sa.Integer(), nullable=True),
            sa.Column("added_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(
                ["organization_id"], ["organizations.id"], ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(["added_by"], ["users.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "organization_id",
                "phone_number_hash",
                "source",
                name="uq_dnc_org_phone_source",
            ),
        )
        op.create_index(
            op.f("ix_compliance_dnc_entries_id"),
            "compliance_dnc_entries",
            ["id"],
            unique=False,
        )
        op.create_index(
            op.f("ix_compliance_dnc_entries_phone_number_hash"),
            "compliance_dnc_entries",
            ["phone_number_hash"],
            unique=False,
        )
        op.create_index(
            "ix_dnc_org_hash",
            "compliance_dnc_entries",
            ["organization_id", "phone_number_hash"],
            unique=False,
        )
        op.create_index(
            "ix_dnc_org_active",
            "compliance_dnc_entries",
            ["organization_id", "is_active"],
            unique=False,
        )

    if not _table_exists("compliance_consent_records"):
        op.create_table(
            "compliance_consent_records",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("organization_id", sa.Integer(), nullable=False),
            sa.Column("phone_number_hash", sa.String(length=64), nullable=False),
            sa.Column("phone_number_e164", sa.String(length=20), nullable=False),
            sa.Column("consent_type", consent_type, nullable=False),
            sa.Column("regulation", regulation, nullable=False),
            sa.Column("consent_source", sa.String(length=500), nullable=True),
            sa.Column("evidence_url", sa.String(length=1000), nullable=True),
            sa.Column(
                "is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")
            ),
            sa.Column("consent_given_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("consent_revoked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_by", sa.Integer(), nullable=True),
            sa.ForeignKeyConstraint(
                ["organization_id"], ["organizations.id"], ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            op.f("ix_compliance_consent_records_id"),
            "compliance_consent_records",
            ["id"],
            unique=False,
        )
        op.create_index(
            op.f("ix_compliance_consent_records_phone_number_hash"),
            "compliance_consent_records",
            ["phone_number_hash"],
            unique=False,
        )
        op.create_index(
            "ix_consent_org_hash",
            "compliance_consent_records",
            ["organization_id", "phone_number_hash"],
            unique=False,
        )
        op.create_index(
            "ix_consent_org_active",
            "compliance_consent_records",
            ["organization_id", "is_active"],
            unique=False,
        )

    if not _table_exists("compliance_audit_log"):
        op.create_table(
            "compliance_audit_log",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("organization_id", sa.Integer(), nullable=False),
            sa.Column("campaign_id", sa.Integer(), nullable=True),
            sa.Column("workflow_run_id", sa.Integer(), nullable=True),
            sa.Column("phone_number_hash", sa.String(length=64), nullable=True),
            sa.Column("action", audit_action, nullable=False),
            sa.Column("regulation", audit_regulation, nullable=True),
            sa.Column(
                "details",
                postgresql.JSONB(),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(
                ["organization_id"], ["organizations.id"], ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(
                ["campaign_id"], ["campaigns.id"], ondelete="SET NULL"
            ),
            sa.ForeignKeyConstraint(
                ["workflow_run_id"], ["workflow_runs.id"], ondelete="SET NULL"
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            op.f("ix_compliance_audit_log_id"),
            "compliance_audit_log",
            ["id"],
            unique=False,
        )
        op.create_index(
            op.f("ix_compliance_audit_log_phone_number_hash"),
            "compliance_audit_log",
            ["phone_number_hash"],
            unique=False,
        )
        op.create_index(
            op.f("ix_compliance_audit_log_created_at"),
            "compliance_audit_log",
            ["created_at"],
            unique=False,
        )
        op.create_index(
            "ix_audit_org_created",
            "compliance_audit_log",
            ["organization_id", "created_at"],
            unique=False,
        )
        op.create_index(
            "ix_audit_org_action",
            "compliance_audit_log",
            ["organization_id", "action"],
            unique=False,
        )
        op.create_index(
            "ix_audit_campaign",
            "compliance_audit_log",
            ["campaign_id"],
            unique=False,
        )

    # Campaign compliance configuration columns
    if not _column_exists("campaigns", "compliance_region"):
        op.add_column(
            "campaigns",
            sa.Column(
                "compliance_region",
                campaign_region,
                nullable=False,
                server_default="us",
            ),
        )
    if not _column_exists("campaigns", "ai_disclosure_enabled"):
        op.add_column(
            "campaigns",
            sa.Column(
                "ai_disclosure_enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("true"),
            ),
        )
    if not _column_exists("campaigns", "ai_disclosure_text"):
        op.add_column(
            "campaigns",
            sa.Column("ai_disclosure_text", sa.String(), nullable=True),
        )
    if not _column_exists("campaigns", "consent_required"):
        op.add_column(
            "campaigns",
            sa.Column(
                "consent_required",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("true"),
            ),
        )
    if not _column_exists("campaigns", "dnc_scrub_enabled"):
        op.add_column(
            "campaigns",
            sa.Column(
                "dnc_scrub_enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("true"),
            ),
        )


def downgrade() -> None:
    for column in (
        "dnc_scrub_enabled",
        "consent_required",
        "ai_disclosure_text",
        "ai_disclosure_enabled",
        "compliance_region",
    ):
        if _column_exists("campaigns", column):
            op.drop_column("campaigns", column)

    for table in (
        "compliance_audit_log",
        "compliance_consent_records",
        "compliance_dnc_entries",
    ):
        if _table_exists(table):
            op.drop_table(table)

    bind = op.get_bind()
    for enum_name in (
        "campaign_compliance_region",
        "compliance_audit_regulation",
        "compliance_audit_action",
        "compliance_regulation",
        "compliance_consent_type",
        "compliance_dnc_source",
    ):
        postgresql.ENUM(name=enum_name).drop(bind, checkfirst=True)
