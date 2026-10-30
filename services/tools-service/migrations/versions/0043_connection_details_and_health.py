"""connection_details_and_health: a connection's card details and each environment's last test (c-580)

The console's Connections grid shows a system connected by name with the category, one line and keys link its admin
gave. Each environment keeps its own Test connection result, so a failing sandbox no longer overwrites the health of a
working production; the connection's own health stays that of the deciding environment. An existing connection's last
result moves onto the row of the environment it tested.

Revision ID: tools_0043_conn_details_health
Revises: tools_0042_plugin_app_keys
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "tools_0043_conn_details_health"
down_revision = "tools_0042_plugin_app_keys"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("connections", sa.Column("category", sa.String(80)))
    op.add_column("connections", sa.Column("description", sa.String(300)))
    op.add_column("connections", sa.Column("docs_url", sa.String(500)))
    op.add_column("connection_environments", sa.Column("health", sa.JSON()))
    # Each connection's last result moves onto the row of the environment it tested, as plain SQL so the revision
    # renders offline for a SQL Server bundle; only the JSON read differs by dialect.
    mssql = op.get_context().dialect.name == "mssql"
    tested = "JSON_VALUE(c.health, '$.environment')" if mssql else "c.health->>'environment'"
    op.execute(
        "UPDATE connection_environments SET health = (SELECT c.health FROM connections c "
        "WHERE c.tenant_id = connection_environments.tenant_id AND c.id = connection_environments.connection_id) "
        "WHERE EXISTS (SELECT 1 FROM connections c WHERE c.tenant_id = connection_environments.tenant_id "
        "AND c.id = connection_environments.connection_id AND c.health IS NOT NULL "
        f"AND {tested} = connection_environments.environment)"
    )


def downgrade() -> None:
    op.drop_column("connection_environments", "health")
    op.drop_column("connections", "docs_url")
    op.drop_column("connections", "description")
    op.drop_column("connections", "category")
