"""Add custom tools and actions tables

Revision ID: 20241223_custom_tools
Revises: 
Create Date: 2024-12-23

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "20241223_custom_tools"
down_revision = "fefdd1835b7d"  # Latest migration: retry_outbound_calls_for_campaigns
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create custom_tools table
    op.create_table(
        "custom_tools",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column(
            "tool_type",
            sa.Enum(
                "http_request",
                "webhook",
                "database_query",
                "custom_code",
                "integration",
                name="tool_type_enum",
            ),
            nullable=False,
        ),
        sa.Column("configuration", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("input_schema", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("output_schema", postgresql.JSONB(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("retry_config", postgresql.JSONB(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), onupdate=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_custom_tools_organization_id", "custom_tools", ["organization_id"])
    op.create_index("ix_custom_tools_name", "custom_tools", ["name"])
    op.create_index("ix_custom_tools_tool_type", "custom_tools", ["tool_type"])
    op.create_unique_constraint("uq_custom_tools_org_name", "custom_tools", ["organization_id", "name"])

    # Create tool_executions table for logging and debugging
    op.create_table(
        "tool_executions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tool_id", sa.Integer(), nullable=False),
        sa.Column("workflow_run_id", sa.Integer(), nullable=True),
        sa.Column(
            "status",
            sa.Enum("pending", "running", "success", "failed", "timeout", name="execution_status_enum"),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("input_data", postgresql.JSONB(), nullable=True),
        sa.Column("output_data", postgresql.JSONB(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("execution_time_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["tool_id"], ["custom_tools.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workflow_run_id"], ["workflow_runs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tool_executions_tool_id", "tool_executions", ["tool_id"])
    op.create_index("ix_tool_executions_workflow_run_id", "tool_executions", ["workflow_run_id"])
    op.create_index("ix_tool_executions_status", "tool_executions", ["status"])
    op.create_index("ix_tool_executions_created_at", "tool_executions", ["created_at"])

    # Create webhook_endpoints table for custom webhook configurations
    op.create_table(
        "webhook_endpoints",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("endpoint_url", sa.Text(), nullable=False),
        sa.Column(
            "http_method",
            sa.Enum("GET", "POST", "PUT", "PATCH", "DELETE", name="http_method_enum"),
            nullable=False,
            server_default="POST",
        ),
        sa.Column("headers", postgresql.JSONB(), nullable=True),
        sa.Column("auth_type", sa.String(length=50), nullable=True),  # none, api_key, bearer, basic, oauth2
        sa.Column("auth_config", postgresql.JSONB(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), onupdate=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_webhook_endpoints_organization_id", "webhook_endpoints", ["organization_id"])


def downgrade() -> None:
    op.drop_table("webhook_endpoints")
    op.drop_table("tool_executions")
    op.drop_table("custom_tools")
    
    # Drop enums
    op.execute("DROP TYPE IF EXISTS tool_type_enum")
    op.execute("DROP TYPE IF EXISTS execution_status_enum")
    op.execute("DROP TYPE IF EXISTS http_method_enum")

