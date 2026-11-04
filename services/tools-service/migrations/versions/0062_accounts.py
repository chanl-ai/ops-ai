"""accounts: an account is one connections row, with a sandbox flag instead of a Test and a Production slot

A connection held a Test and a Production slot (connection_environments), each with its own settings, secrets, health,
sign-in app and plugin settings, and every token, sign-in state and connect link named one of them. An account is now
one connections row: its slot's columns move onto it, `sandbox` marks an account a test run uses, and `app_id` names
the app it belongs to (`plugin:<id>` for a plugin's, the custom app's own connection id for a custom app's), replacing
`plugin_id`, so a custom app's sandbox account is found the way a plugin's is. app_credentials.app_id takes the same
form.

A connection with only a Production slot keeps it. One with only a Test slot becomes a sandbox account under its id.
One with both keeps its id for Production, and its Test slot becomes a new sandbox account (`<id>_sandbox`, named
"<name> sandbox") whose secret rows move to it under their names, which are the secrets' cipher context.

Stored tokens, sign-in states and connect links are deleted: a token is sealed with its connection and slot, so it
cannot move, and each account is signed in again once (owner, 2026-11-03). The downgrade folds each split sandbox back
into its connection's Test slot and makes every other sandbox account a Test-only connection; tokens are not restored.

Revision ID: tools_0062_accounts
Revises: tools_0061_app_credentials
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mssql

from ops_store.schema import TEAM_OWNED, TENANT_SCOPED, isolation_ddl, isolation_drop_ddl, mssql_predicates_ddl

revision = "tools_0062_accounts"
down_revision = "tools_0061_app_credentials"
branch_labels = None
depends_on = None

CHAIN = "tools"
ROLE = "ops_tools_tenant"
_TS = sa.DateTime(timezone=True)
# The columns a slot held that an account now holds itself.
MOVED = ("settings", "secrets", "health", "platform_app", "credential_id", "plugin_settings")
# Every column of connections a split sandbox account copies from its connection, as 0061 left them.
COPIED = (
    "tenant_id", "team_id", "auth_kind", "status", "status_detail", "expires_at", "catalog_id", "sign_in",
    "team_backup", "category", "description", "docs_url", "plugin_id", "origin", "created_by", "created_at",
    "updated_by", "updated_at", "app_id",
)  # fmt: skip
# The split sandbox's id: its connection's id, cut so the suffix fits the column.
SANDBOX_ID = "CONCAT(LEFT(c.id, 56), '_sandbox')"


def _marked() -> sa.Table:
    return sa.Table(
        "connection_environments",
        sa.MetaData(),
        sa.Column("tenant_id", sa.String(64)),
        sa.Column("team_id", sa.String(64)),
        info={**TENANT_SCOPED, **TEAM_OWNED},
    )


def _column_type(column: sa.Column[Any]) -> str:
    return column.type.compile(dialect=mssql.dialect())


def _slot(environment: str, column: str) -> str:
    return (
        f"(SELECT e.{column} FROM connection_environments e WHERE e.tenant_id = connections.tenant_id "
        f"AND e.connection_id = connections.id AND e.environment = '{environment}')"
    )


def _has(environment: str, alias: str = "connections") -> str:
    return (
        f"EXISTS (SELECT 1 FROM connection_environments e WHERE e.tenant_id = {alias}.tenant_id "
        f"AND e.connection_id = {alias}.id AND e.environment = '{environment}')"
    )


def upgrade() -> None:
    dialect = op.get_context().dialect.name
    true = "1" if dialect == "mssql" else "true"
    if dialect == "postgresql":
        # The migrating role may own the tables; once FORCE is on, row-level security would hide rows from it.
        op.execute("SET LOCAL row_security = off")
    op.add_column("connections", sa.Column("settings", sa.JSON))
    op.add_column("connections", sa.Column("secrets", sa.JSON))
    op.add_column("connections", sa.Column("platform_app", sa.String(120)))
    op.add_column("connections", sa.Column("credential_id", sa.String(64)))
    op.add_column("connections", sa.Column("plugin_settings", sa.JSON))
    op.add_column("connections", sa.Column("sandbox", sa.Boolean, nullable=False, server_default=sa.false()))
    op.add_column("connections", sa.Column("app_id", sa.String(120)))
    op.execute(
        "UPDATE connections SET app_id = CASE WHEN plugin_id IS NULL THEN id ELSE CONCAT('plugin:', plugin_id) END"
    )
    op.execute(
        "UPDATE app_credentials SET app_id = CONCAT('plugin:', app_id) WHERE EXISTS (SELECT 1 FROM connections c "
        "WHERE c.tenant_id = app_credentials.tenant_id AND c.plugin_id = app_credentials.app_id)"
    )
    # A connection with both slots: its Test slot becomes a sandbox account of its own, which moves its secret rows.
    both = f"{_has('production', 'c')} AND {_has('test', 'c')}"
    moved = ", ".join(f"e.{m}" for m in MOVED)
    op.execute(
        f"INSERT INTO connections (id, name, account_name, revision, sandbox, {', '.join(COPIED)}, {', '.join(MOVED)}) "
        f"SELECT {SANDBOX_ID}, CONCAT(c.name, ' sandbox'), "
        "CASE WHEN c.account_name IS NULL THEN NULL ELSE CONCAT(c.account_name, ' sandbox') END, 1, "
        f"{true}, {', '.join('c.' + k for k in COPIED)}, {moved} "
        "FROM connections c JOIN connection_environments e ON e.tenant_id = c.tenant_id AND e.connection_id = c.id "
        f"AND e.environment = 'test' WHERE {both}"
    )
    if dialect == "mssql":
        names = (
            "SELECT e.tenant_id, e.connection_id, j.[value] AS name FROM connection_environments e "
            "CROSS APPLY OPENJSON(e.secrets) j WHERE e.environment = 'test'"
        )
    else:
        names = (
            "SELECT e.tenant_id, e.connection_id, j.value AS name FROM connection_environments e, "
            "json_each_text(e.secrets) j WHERE e.environment = 'test'"
        )
    names += (
        " UNION SELECT e.tenant_id, e.connection_id, a.secret_name FROM connection_environments e "
        "JOIN app_credentials a ON a.tenant_id = e.tenant_id AND a.id = e.credential_id "
        "WHERE e.environment = 'test' AND a.secret_name IS NOT NULL"
    )
    op.execute(
        f"UPDATE tool_secrets SET connection_id = (SELECT {SANDBOX_ID} FROM connections c "
        "WHERE c.tenant_id = tool_secrets.tenant_id AND c.id = tool_secrets.connection_id) "
        f"WHERE EXISTS (SELECT 1 FROM ({names}) n JOIN connections c ON c.tenant_id = n.tenant_id "
        "AND c.id = n.connection_id WHERE n.tenant_id = tool_secrets.tenant_id "
        f"AND n.connection_id = tool_secrets.connection_id AND n.name = tool_secrets.name AND {both})"
    )
    # Every other connection takes its Production slot, else its Test slot as a sandbox account, else nothing.
    for environment, flag in (("production", None), ("test", true)):
        values = ", ".join(f"{m} = {_slot(environment, m)}" for m in MOVED)
        mark = f", sandbox = {flag}" if flag else ""
        op.execute(f"UPDATE connections SET {values}{mark} WHERE settings IS NULL AND {_has(environment)}")
    op.execute("UPDATE connections SET settings = '{}', secrets = '{}' WHERE settings IS NULL")
    op.alter_column("connections", "settings", existing_type=sa.JSON, nullable=False)
    op.alter_column("connections", "secrets", existing_type=sa.JSON, nullable=False)
    op.alter_column("connections", "app_id", existing_type=sa.String(120), nullable=False)
    op.drop_column("connections", "plugin_id")
    op.create_index("ix_connections_app", "connections", ["tenant_id", "team_id", "app_id"])
    for table in ("connection_tokens", "oauth_states", "connect_links"):
        op.execute(f"DELETE FROM {table}")
    op.drop_constraint("connection_tokens_pkey", "connection_tokens", type_="primary")
    op.drop_column("connection_tokens", "environment")
    op.create_primary_key("connection_tokens_pkey", "connection_tokens", ["tenant_id", "connection_id", "person_id"])
    op.drop_column("oauth_states", "environment")
    op.drop_column("connect_links", "environment")
    if dialect in ("postgresql", "mssql"):
        for statement in isolation_drop_ddl(_marked(), dialect):
            op.execute(statement)
    op.drop_table("connection_environments")


def downgrade() -> None:
    dialect = op.get_context().dialect.name
    if dialect == "postgresql":
        op.execute("SET LOCAL row_security = off")
    op.create_table(
        "connection_environments",
        sa.Column("tenant_id", sa.String(64), primary_key=True),
        sa.Column("connection_id", sa.String(64), primary_key=True),
        sa.Column("environment", sa.String(16), primary_key=True),
        sa.Column("team_id", sa.String(64), nullable=False),
        sa.Column("settings", sa.JSON, nullable=False),
        sa.Column("secrets", sa.JSON, nullable=False),
        sa.Column("health", sa.JSON),
        sa.Column("platform_app", sa.String(120)),
        sa.Column("credential_id", sa.String(64)),
        sa.Column("plugin_settings", sa.JSON),
        sa.Column("updated_by", sa.String(200), nullable=False),
        sa.Column("updated_at", _TS, nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "connection_id"], ["connections.tenant_id", "connections.id"], ondelete="CASCADE"
        ),
    )
    true = "1" if dialect == "mssql" else "true"
    moved = ", ".join(MOVED)
    # A sandbox the upgrade split off goes back into its connection's Test slot, its secret rows with it.
    split = (
        f"SELECT s.* FROM connections s JOIN connections c ON c.tenant_id = s.tenant_id AND s.id = {SANDBOX_ID} "
        f"WHERE s.sandbox = {true} AND c.sandbox <> {true}"
    )
    op.execute(
        f"INSERT INTO connection_environments (tenant_id, connection_id, environment, team_id, {moved}, updated_by, "
        f"updated_at) SELECT c.tenant_id, c.id, 'test', c.team_id, {', '.join('s.' + m for m in MOVED)}, s.updated_by, "
        f"s.updated_at FROM connections c JOIN ({split}) s ON s.tenant_id = c.tenant_id AND s.id = {SANDBOX_ID}"
    )
    op.execute(
        "UPDATE tool_secrets SET connection_id = (SELECT c.id FROM connections c WHERE c.tenant_id = "
        f"tool_secrets.tenant_id AND {SANDBOX_ID} = tool_secrets.connection_id) WHERE EXISTS (SELECT 1 FROM "
        f"connections c WHERE c.tenant_id = tool_secrets.tenant_id AND {SANDBOX_ID} = tool_secrets.connection_id)"
    )
    op.execute(
        "DELETE FROM connections WHERE EXISTS (SELECT 1 FROM connections c WHERE c.tenant_id = connections.tenant_id "
        f"AND {SANDBOX_ID} = connections.id AND c.sandbox <> {true}) AND sandbox = {true}"
    )
    op.execute(
        f"INSERT INTO connection_environments (tenant_id, connection_id, environment, team_id, {moved}, updated_by, "
        f"updated_at) SELECT tenant_id, id, CASE WHEN sandbox = {true} THEN 'test' ELSE 'production' END, team_id, "
        f"{moved}, updated_by, updated_at FROM connections"
    )
    op.add_column("connections", sa.Column("plugin_id", sa.String(120)))
    op.execute("UPDATE connections SET plugin_id = SUBSTRING(app_id, 8, 120) WHERE app_id LIKE 'plugin:%'")
    op.execute("UPDATE app_credentials SET app_id = SUBSTRING(app_id, 8, 120) WHERE app_id LIKE 'plugin:%'")
    op.drop_index("ix_connections_app", "connections")
    for column in (*MOVED[:2], *MOVED[3:], "app_id"):
        op.drop_column("connections", column)
    # SQL Server holds the flag's default as a constraint of its own, which has to go first.
    op.drop_column("connections", "sandbox", mssql_drop_default=True)
    for table in ("connection_tokens", "oauth_states", "connect_links"):
        op.execute(f"DELETE FROM {table}")
    op.add_column("oauth_states", sa.Column("environment", sa.String(16), nullable=False, server_default="production"))
    op.add_column("connect_links", sa.Column("environment", sa.String(16), nullable=False, server_default="production"))
    op.drop_constraint("connection_tokens_pkey", "connection_tokens", type_="primary")
    op.add_column(
        "connection_tokens", sa.Column("environment", sa.String(16), nullable=False, server_default="production")
    )
    op.create_primary_key(
        "connection_tokens_pkey", "connection_tokens", ["tenant_id", "connection_id", "environment", "person_id"]
    )
    table = _marked()
    if dialect == "postgresql":
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON connection_environments TO {ROLE}")
    elif dialect == "mssql":
        for statement in mssql_predicates_ddl(CHAIN, [table], column_type=_column_type, system_user=None):
            op.execute(statement)
    else:
        return
    for statement in isolation_ddl(table, dialect, chain=CHAIN):
        op.execute(statement)
