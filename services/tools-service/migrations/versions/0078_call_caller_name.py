"""gateway_calls.caller_name: the caller's name when the call was made

The log kept a person's or key's id only, so an MCP link's Calls tab named people by id. The name the token carried
is now kept beside it.

Revision ID: tools_0078_call_caller_name
Revises: tools_0077_mcp_links
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "tools_0078_call_caller_name"
down_revision = "tools_0077_mcp_links"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("gateway_calls", sa.Column("caller_name", sa.String(320)))


def downgrade() -> None:
    op.drop_column("gateway_calls", "caller_name")
