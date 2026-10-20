"""gateway_calls.channel and client_name: which route took a call and the client that sent it (c-356)

Every call came through POST /v1/calls from a run. Calls now also arrive over MCP from outside assistants, and the log
has to say which route took each one and which client sent it (a claim the client makes, shown as one).

Revision ID: tools_0030_call_channel
Revises: tools_0029_operation_mocks
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "tools_0030_call_channel"
down_revision = "tools_0029_operation_mocks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("gateway_calls", sa.Column("channel", sa.String(16)))
    op.add_column("gateway_calls", sa.Column("client_name", sa.String(120)))


def downgrade() -> None:
    op.drop_column("gateway_calls", "client_name")
    op.drop_column("gateway_calls", "channel")
