"""gateway_calls.client_id: the assistant an MCP token was issued to

The log named an assistant by what it said about itself (clientInfo), which anyone can set to anything. A token issued
through platform-service's authorization server carries the registered client's id, and the log now keeps it.

Revision ID: tools_0075_call_client_id
Revises: tools_0074_stored_waits_answers
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "tools_0075_call_client_id"
down_revision = "tools_0074_stored_waits_answers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("gateway_calls", sa.Column("client_id", sa.String(64)))


def downgrade() -> None:
    op.drop_column("gateway_calls", "client_id")
