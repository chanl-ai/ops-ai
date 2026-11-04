"""team_credentials: an app credential is the team's, made with no account, and its secret belongs to it

An app credential was made by an account's write and kept its name, permissions and client secret on that account: the
secret's tool_secrets row named the account (connection_id), and deleting the account took the credential with it. A
credential is now made under Credentials on its own and accounts pick it, so it keeps its own name and permissions
(`name`, `scopes`, taken from the account it was made on), and its secret row names the credential (`credential_id`)
instead of an account. The secret keeps its name, which is its cipher context.

Revision ID: tools_0064_team_credentials
Revises: tools_0063_health_slot
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "tools_0064_team_credentials"
down_revision = "tools_0063_health_slot"
branch_labels = None
depends_on = None

# The account a credential was made on: the oldest of those signing in with it.
_ON = "connections c WHERE c.tenant_id = app_credentials.tenant_id AND c.credential_id = app_credentials.id"
_SECRET = (
    "app_credentials a WHERE a.tenant_id = tool_secrets.tenant_id AND a.team_id = tool_secrets.team_id "
    "AND a.secret_name = tool_secrets.name"
)


def upgrade() -> None:
    dialect = op.get_context().dialect.name
    if dialect == "postgresql":
        # The migrating role may own the tables; once FORCE is on, row-level security would hide rows from it.
        op.execute("SET LOCAL row_security = off")
    op.add_column("app_credentials", sa.Column("name", sa.String(200)))
    op.add_column("app_credentials", sa.Column("scopes", sa.String(2000)))
    op.add_column("tool_secrets", sa.Column("credential_id", sa.String(64)))
    scopes = (
        "JSON_VALUE(c.settings, '$.scopes')" if dialect == "mssql" else "json_extract_path_text(c.settings, 'scopes')"
    )
    op.execute(
        f"UPDATE app_credentials SET name = COALESCE((SELECT MIN(COALESCE(c.account_name, c.name)) FROM {_ON}), "
        f"app_id), scopes = (SELECT MIN({scopes}) FROM {_ON})"
    )
    op.alter_column("app_credentials", "name", existing_type=sa.String(200), nullable=False)
    op.execute(
        f"UPDATE tool_secrets SET credential_id = (SELECT MIN(a.id) FROM {_SECRET}), connection_id = NULL "
        f"WHERE EXISTS (SELECT 1 FROM {_SECRET})"
    )


def downgrade() -> None:
    dialect = op.get_context().dialect.name
    if dialect == "postgresql":
        op.execute("SET LOCAL row_security = off")
    op.execute(
        "UPDATE tool_secrets SET connection_id = (SELECT MIN(c.id) FROM connections c "
        "WHERE c.tenant_id = tool_secrets.tenant_id AND c.credential_id = tool_secrets.credential_id) "
        "WHERE credential_id IS NOT NULL"
    )
    op.drop_column("tool_secrets", "credential_id")
    op.drop_column("app_credentials", "scopes")
    op.drop_column("app_credentials", "name")
