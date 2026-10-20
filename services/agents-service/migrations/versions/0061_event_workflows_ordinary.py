"""engine_definitions: drop `system`; the workflows a service event starts are ordinary workflows (c-258)

A system workflow was copied from code into the database on its tenant's first event and then refused to every person:
nobody could edit, publish, pause or run it. The event workflows are now ordinary rows owned by no team, edited and
published through review, and the event's handler is found by its workflow id, so the flag has no reader left.

Revision ID: 0061_event_workflows_ordinary
Revises: 0060_service_events
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0061_event_workflows_ordinary"
down_revision = "0060_service_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("engine_definitions", "system")


def downgrade() -> None:
    op.add_column("engine_definitions", sa.Column("system", sa.Boolean(), nullable=False, server_default=sa.false()))
