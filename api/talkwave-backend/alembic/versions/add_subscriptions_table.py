"""add subscriptions table

Revision ID: add_subscriptions_001
Revises: 
Create Date: 2026-02-07

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'add_subscriptions_001'
down_revision: Union[str, None] = '20260103_kb'
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
    if _table_exists("subscriptions"):
        return

    op.create_table(
        'subscriptions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('organization_id', sa.Integer(), nullable=False),
        sa.Column('plan', sa.String(length=50), nullable=False, server_default='trial'),
        sa.Column('status', sa.String(length=50), nullable=False, server_default='active'),
        sa.Column('stripe_customer_id', sa.String(length=255), nullable=True),
        sa.Column('stripe_subscription_id', sa.String(length=255), nullable=True),
        sa.Column('stripe_price_id', sa.String(length=255), nullable=True),
        sa.Column('minutes_included', sa.Integer(), nullable=False, server_default='15'),
        sa.Column('minutes_used', sa.Float(), nullable=False, server_default='0'),
        sa.Column('overage_rate_per_minute', sa.Float(), nullable=True),
        sa.Column('max_workflows', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('max_campaign_contacts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('gemini_s2s_enabled', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('trial_minutes_total', sa.Integer(), nullable=False, server_default='15'),
        sa.Column('trial_started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('trial_expired', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('current_period_start', sa.DateTime(timezone=True), nullable=True),
        sa.Column('current_period_end', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('canceled_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('organization_id'),
        sa.UniqueConstraint('stripe_customer_id'),
        sa.UniqueConstraint('stripe_subscription_id'),
    )
    op.create_index('ix_subscriptions_organization_id', 'subscriptions', ['organization_id'], unique=False)
    op.create_index('ix_subscriptions_stripe_customer_id', 'subscriptions', ['stripe_customer_id'], unique=False)
    op.create_index('ix_subscriptions_stripe_subscription_id', 'subscriptions', ['stripe_subscription_id'], unique=False)
    op.create_index('ix_subscriptions_plan', 'subscriptions', ['plan'], unique=False)
    op.create_index('ix_subscriptions_status', 'subscriptions', ['status'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_subscriptions_status', table_name='subscriptions')
    op.drop_index('ix_subscriptions_plan', table_name='subscriptions')
    op.drop_index('ix_subscriptions_stripe_subscription_id', table_name='subscriptions')
    op.drop_index('ix_subscriptions_stripe_customer_id', table_name='subscriptions')
    op.drop_index('ix_subscriptions_organization_id', table_name='subscriptions')
    op.drop_table('subscriptions')

