"""add opaque public_id to workflows

Revision ID: 20260721_wf_pubid
Revises: e1f2a3b4c5d6
Create Date: 2026-07-21

Adds a high-entropy, unguessable ``public_id`` to workflows. This token is used
in externally-exposed URLs (e.g. the Twilio inbound webhook
``/telephony/inbound/{public_id}``) so that the enumerable sequential integer
primary key is never exposed in semi-public locations. Existing rows are
backfilled with unique tokens.
"""
import secrets
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260721_wf_pubid"
down_revision: Union[str, None] = "e1f2a3b4c5d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


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


def upgrade():
    if _column_exists("workflows", "public_id"):
        return

    op.add_column(
        "workflows",
        sa.Column("public_id", sa.String(), nullable=True),
    )

    # Backfill existing rows with unique high-entropy tokens.
    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT id FROM workflows")).fetchall()
    used: set[str] = set()
    for (workflow_id,) in rows:
        token = secrets.token_urlsafe(16)
        while token in used:
            token = secrets.token_urlsafe(16)
        used.add(token)
        conn.execute(
            sa.text("UPDATE workflows SET public_id = :pid WHERE id = :id"),
            {"pid": token, "id": workflow_id},
        )

    op.create_index(
        "ix_workflows_public_id",
        "workflows",
        ["public_id"],
        unique=True,
    )


def downgrade():
    op.drop_index("ix_workflows_public_id", table_name="workflows")
    op.drop_column("workflows", "public_id")
