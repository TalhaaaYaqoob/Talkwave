"""add workflow_improvements table

Revision ID: b7c8d9e0f1a2
Revises: a1b2c3d4e5f6
Create Date: 2026-04-15 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b7c8d9e0f1a2"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(name: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(
        sa.text("SELECT 1 FROM information_schema.tables WHERE table_name = :t"),
        {"t": name},
    )
    return result.scalar() is not None


def upgrade() -> None:
    improvement_status = sa.Enum(
        "pending", "accepted", "rejected", "auto_applied",
        name="improvement_status",
    )
    improvement_status.create(op.get_bind(), checkfirst=True)

    if not _table_exists("workflow_improvements"):
        op.create_table(
            "workflow_improvements",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column(
                "workflow_id",
                sa.Integer(),
                sa.ForeignKey("workflows.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "organization_id",
                sa.Integer(),
                sa.ForeignKey("organizations.id"),
                nullable=False,
            ),
            sa.Column("status", improvement_status, nullable=False, server_default="pending"),
            sa.Column("suggestions", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("analysis_summary", sa.Text(), nullable=True),
            sa.Column("calls_analyzed", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_run_id_analyzed", sa.Integer(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
            ),
        )

        op.create_index("ix_workflow_improvements_workflow_id", "workflow_improvements", ["workflow_id"])
        op.create_index("ix_workflow_improvements_status", "workflow_improvements", ["status"])
        op.create_index(
            "ix_workflow_improvements_workflow_status",
            "workflow_improvements",
            ["workflow_id", "status"],
        )


def downgrade() -> None:
    op.drop_index("ix_workflow_improvements_workflow_status", table_name="workflow_improvements")
    op.drop_index("ix_workflow_improvements_status", table_name="workflow_improvements")
    op.drop_index("ix_workflow_improvements_workflow_id", table_name="workflow_improvements")
    op.drop_table("workflow_improvements")
    sa.Enum(name="improvement_status").drop(op.get_bind(), checkfirst=True)
