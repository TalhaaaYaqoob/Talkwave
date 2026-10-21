"""add workflow_id to knowledge_base_documents

Revision ID: 20260302_kb_wf
Revises: add_subscriptions_001
Create Date: 2026-03-02

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260302_kb_wf"
down_revision: Union[str, None] = "add_subscriptions_001"
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
    if _column_exists("knowledge_base_documents", "workflow_id"):
        return

    op.add_column(
        "knowledge_base_documents",
        sa.Column("workflow_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_kb_documents_workflow_id",
        "knowledge_base_documents",
        "workflows",
        ["workflow_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_kb_documents_workflow_id",
        "knowledge_base_documents",
        ["workflow_id"],
        unique=False,
    )


def downgrade():
    op.drop_index("ix_kb_documents_workflow_id", table_name="knowledge_base_documents")
    op.drop_constraint(
        "fk_kb_documents_workflow_id", "knowledge_base_documents", type_="foreignkey"
    )
    op.drop_column("knowledge_base_documents", "workflow_id")
