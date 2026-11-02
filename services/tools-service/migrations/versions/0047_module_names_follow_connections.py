"""module_names_follow_connections: a module's sign-in says person_or_team, as a connection's does (c-591)

A module stored `either` where connections say `person_or_team` for the same choice. Rows move to the connections' name
and the column's default follows; the API still reads `either` for one release (connections/records.py sign_in_of).
A module's auth kind is not a column: it is read from the stored auth in the connections' names (records.auth_of).

Revision ID: tools_0047_module_names
Revises: tools_0046_env_app_settings
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "tools_0047_module_names"
down_revision = "tools_0046_env_app_settings"
branch_labels = None
depends_on = None

CHAIN = "tools"


def upgrade() -> None:
    if op.get_context().dialect.name == "postgresql":
        # The migrating role may own the table; FORCE row-level security would otherwise hide every row from it.
        op.execute("SET LOCAL row_security = off")
    op.execute("UPDATE tool_modules SET sign_in = 'person_or_team' WHERE sign_in = 'either'")
    op.alter_column(
        "tool_modules",
        "sign_in",
        existing_type=sa.String(16),
        existing_nullable=False,
        existing_server_default="either",
        server_default="person_or_team",
    )


def downgrade() -> None:
    pass
