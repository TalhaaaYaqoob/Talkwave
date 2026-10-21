"""add campaign scheduling fields

Revision ID: a1b2c3d4e5f6
Revises: fefdd1835b7d
Create Date: 2026-02-15 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "fefdd1835b7d"
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


def upgrade() -> None:
    op.execute("ALTER TYPE campaign_state ADD VALUE IF NOT EXISTS 'scheduled' BEFORE 'syncing'")

    if not _column_exists("campaigns", "scheduled_start_at"):
        op.add_column(
            "campaigns",
            sa.Column("scheduled_start_at", sa.DateTime(timezone=True), nullable=True),
        )
    if not _column_exists("campaigns", "calling_window_start"):
        op.add_column(
            "campaigns",
            sa.Column("calling_window_start", sa.String(), nullable=True),
        )
    if not _column_exists("campaigns", "calling_window_end"):
        op.add_column(
            "campaigns",
            sa.Column("calling_window_end", sa.String(), nullable=True),
        )
    if not _column_exists("campaigns", "calling_window_timezone"):
        op.add_column(
            "campaigns",
            sa.Column("calling_window_timezone", sa.String(), nullable=True, server_default="UTC"),
        )

    try:
        op.drop_index("idx_campaigns_active_status", table_name="campaigns")
    except Exception:
        pass
    op.create_index(
        "idx_campaigns_active_status",
        "campaigns",
        ["state"],
        postgresql_where=sa.text("state IN ('scheduled', 'syncing', 'running', 'paused')"),
    )


def downgrade() -> None:
    # Restore original partial index
    op.drop_index("idx_campaigns_active_status", table_name="campaigns")
    op.create_index(
        "idx_campaigns_active_status",
        "campaigns",
        ["state"],
        postgresql_where=sa.text("state IN ('syncing', 'running', 'paused')"),
    )

    # Drop scheduling columns
    op.drop_column("campaigns", "calling_window_timezone")
    op.drop_column("campaigns", "calling_window_end")
    op.drop_column("campaigns", "calling_window_start")
    op.drop_column("campaigns", "scheduled_start_at")

    # Note: PostgreSQL doesn't support removing enum values directly.
    # The 'scheduled' value will remain in the enum type.
