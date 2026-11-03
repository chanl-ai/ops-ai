"""app_accounts: a team keeps several named accounts of one app

A team held one connection per plugin and a person one sign-in per connection, so a second Salesforce org or a
second account of the same app could not be connected. An app's accounts are now its connections that name the
plugin, each with a name a tool or step uses; the binding's connection stays the default. A person pins one of
their sign-ins as their default. Each plugin's existing connection takes its plugin id and its name as the account's.

Revision ID: tools_0050_app_accounts
Revises: tools_0049_binding_versions
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "tools_0050_app_accounts"
down_revision = "tools_0049_binding_versions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("connections", sa.Column("plugin_id", sa.String(120)))
    op.add_column("connections", sa.Column("account_name", sa.String(200)))
    op.add_column("connection_tokens", sa.Column("pinned", sa.Boolean, nullable=False, server_default=sa.false()))
    conn = sa.table(
        "connections",
        sa.column("tenant_id", sa.String),
        sa.column("id", sa.String),
        sa.column("name", sa.String),
        sa.column("plugin_id", sa.String),
        sa.column("account_name", sa.String),
    )
    binding = sa.table(
        "plugin_bindings",
        sa.column("tenant_id", sa.String),
        sa.column("plugin_id", sa.String),
        sa.column("connection_id", sa.String),
    )
    named = sa.select(binding.c.plugin_id).where(
        binding.c.tenant_id == conn.c.tenant_id, binding.c.connection_id == conn.c.id
    )
    # Correlated subqueries rather than UPDATE ... FROM, which PostgreSQL and SQL Server write differently.
    op.execute(
        conn.update()
        .where(sa.exists(named))
        .values(plugin_id=named.limit(1).scalar_subquery(), account_name=conn.c.name)
    )


def downgrade() -> None:
    # The `ca_` ids are rows, not schema; a downgrade keeps the connections and drops only what the upgrade added.
    op.drop_column("connection_tokens", "pinned", mssql_drop_default=True)
    op.drop_column("connections", "account_name")
    op.drop_column("connections", "plugin_id")
