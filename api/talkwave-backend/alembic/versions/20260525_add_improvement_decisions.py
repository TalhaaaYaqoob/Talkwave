"""add applied_indices and rejected_indices to workflow_improvements

Revision ID: c8d9e0f1a2b3
Revises: b7c8d9e0f1a2
Create Date: 2026-05-25 00:00:00.000000

Adds per-suggestion accept/reject tracking to workflow_improvements so the
self-improving agent UI can render per-row decisions instead of a single
batch apply/dismiss.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c8d9e0f1a2b3"
down_revision: Union[str, None] = "b7c8d9e0f1a2"
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
    if not _column_exists("workflow_improvements", "applied_indices"):
        op.add_column(
            "workflow_improvements",
            sa.Column(
                "applied_indices",
                sa.JSON(),
                nullable=False,
                server_default="[]",
            ),
        )
    if not _column_exists("workflow_improvements", "rejected_indices"):
        op.add_column(
            "workflow_improvements",
            sa.Column(
                "rejected_indices",
                sa.JSON(),
                nullable=False,
                server_default="[]",
            ),
        )


def downgrade() -> None:
    if _column_exists("workflow_improvements", "rejected_indices"):
        op.drop_column("workflow_improvements", "rejected_indices")
    if _column_exists("workflow_improvements", "applied_indices"):
        op.drop_column("workflow_improvements", "applied_indices")
