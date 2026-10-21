"""bump default idle / silence / call-duration timeouts for existing workflows

Revision ID: d9e0f1a2b3c4
Revises: c8d9e0f1a2b3
Create Date: 2026-05-26 17:30:00.000000

Real-world testing showed:
  - `max_user_idle_timeout = 7.0` was so aggressive that the silence callback
    fired in the middle of normal turn-taking pauses, making the call feel
    "stuck" every few exchanges.
  - `max_call_duration = 300` (5 min) cut realistic conversations off.
  - `max_cumulative_silence = 20.0` triggered too early on thoughtful callers.

The application defaults have been raised. This migration updates every
existing workflow whose JSON config still carries the OLD platform-seeded
values (so we don't overwrite values the user explicitly tuned themselves).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d9e0f1a2b3c4"
down_revision: Union[str, None] = "c8d9e0f1a2b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # Idle timeout: 7.0 → 18.0 (only where it was the old platform default)
    conn.execute(
        sa.text(
            """
            UPDATE workflows
            SET workflow_configurations =
                jsonb_set(
                    workflow_configurations::jsonb,
                    '{max_user_idle_timeout}',
                    '18.0'::jsonb,
                    true
                )::json
            WHERE (workflow_configurations::jsonb ->> 'max_user_idle_timeout')::float = 7.0
            """
        )
    )

    # Call duration: 300 → 600
    conn.execute(
        sa.text(
            """
            UPDATE workflows
            SET workflow_configurations =
                jsonb_set(
                    workflow_configurations::jsonb,
                    '{max_call_duration}',
                    '600'::jsonb,
                    true
                )::json
            WHERE (workflow_configurations::jsonb ->> 'max_call_duration')::int = 300
            """
        )
    )

    # Cumulative silence: 20.0 → 30.0
    conn.execute(
        sa.text(
            """
            UPDATE workflows
            SET workflow_configurations =
                jsonb_set(
                    workflow_configurations::jsonb,
                    '{max_cumulative_silence}',
                    '30.0'::jsonb,
                    true
                )::json
            WHERE (workflow_configurations::jsonb ->> 'max_cumulative_silence')::float = 20.0
            """
        )
    )


def downgrade() -> None:
    # Best-effort revert: flip values back to the old defaults wherever the
    # current value matches what we wrote in `upgrade`.
    conn = op.get_bind()

    conn.execute(
        sa.text(
            """
            UPDATE workflows
            SET workflow_configurations =
                jsonb_set(
                    workflow_configurations::jsonb,
                    '{max_user_idle_timeout}',
                    '7.0'::jsonb,
                    true
                )::json
            WHERE (workflow_configurations::jsonb ->> 'max_user_idle_timeout')::float = 18.0
            """
        )
    )
    conn.execute(
        sa.text(
            """
            UPDATE workflows
            SET workflow_configurations =
                jsonb_set(
                    workflow_configurations::jsonb,
                    '{max_call_duration}',
                    '300'::jsonb,
                    true
                )::json
            WHERE (workflow_configurations::jsonb ->> 'max_call_duration')::int = 600
            """
        )
    )
    conn.execute(
        sa.text(
            """
            UPDATE workflows
            SET workflow_configurations =
                jsonb_set(
                    workflow_configurations::jsonb,
                    '{max_cumulative_silence}',
                    '20.0'::jsonb,
                    true
                )::json
            WHERE (workflow_configurations::jsonb ->> 'max_cumulative_silence')::float = 30.0
            """
        )
    )
