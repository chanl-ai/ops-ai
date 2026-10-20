"""engine_steps.node_type: each step names its node type, so steps can be listed by kind without reading definitions

Revision ID: 0057_engine_step_node_type
Revises: 0056_trigger_events

Activity lists a workflow's tool calls (c-201) from the steps whose node type calls the tool gateway. Steps journaled
before this have none and are not listed.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0057_engine_step_node_type"
down_revision = "0056_trigger_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("engine_steps", sa.Column("node_type", sa.String(80)))


def downgrade() -> None:
    op.drop_column("engine_steps", "node_type")
