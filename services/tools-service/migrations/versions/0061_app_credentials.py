"""app_credentials: a team's own OAuth client of an app is kept once, and Ops AI's app comes only from the install

A team's client id was a key of each environment's settings and its secret a name in each environment's secrets, so
two accounts of one app held two copies; Ops AI's app had a client id in the plugins policy, a copy in each
environment's settings, a secret sealed per tenant in plugin_app_keys, and a third source in the install config. The
team's client now lives in app_credentials, which an environment names by credential_id; Ops AI's app is the install
config's (plugin_clients) alone, named by the environment's platform_app. The existing clients move with their values;
plugin_app_keys is dropped (its secrets were set by hand on development stacks and come from the install config now).

Revision ID: tools_0061_app_credentials
Revises: tools_0060_account_test
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mssql

from ops_store.schema import TEAM_OWNED, TENANT_SCOPED, isolation_ddl, isolation_drop_ddl, mssql_predicates_ddl

revision = "tools_0061_app_credentials"
down_revision = "tools_0060_account_test"
branch_labels = None
depends_on = None

CHAIN = "tools"
ROLE = "ops_tools_tenant"
_TS = sa.DateTime(timezone=True)


def _marked() -> sa.Table:
    return sa.Table(
        "app_credentials",
        sa.MetaData(),
        sa.Column("tenant_id", sa.String(64)),
        sa.Column("team_id", sa.String(64)),
        info={**TENANT_SCOPED, **TEAM_OWNED},
    )


def _column_type(column: sa.Column[Any]) -> str:
    return column.type.compile(dialect=mssql.dialect())


def upgrade() -> None:
    dialect = op.get_context().dialect.name
    if dialect == "postgresql":
        # The migrating role may own the tables; once FORCE is on, row-level security would hide rows from it.
        op.execute("SET LOCAL row_security = off")
    op.create_table(
        "app_credentials",
        sa.Column("tenant_id", sa.String(64), primary_key=True),
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("team_id", sa.String(64), nullable=False),
        sa.Column("app_id", sa.String(120), nullable=False),
        sa.Column("client_id", sa.String(500), nullable=False),
        sa.Column("secret_name", sa.String(200)),
        sa.Column("created_by", sa.String(200), nullable=False),
        sa.Column("created_at", _TS, nullable=False),
        sa.Column("updated_by", sa.String(200), nullable=False),
        sa.Column("updated_at", _TS, nullable=False),
    )
    op.add_column("connection_environments", sa.Column("credential_id", sa.String(64)))
    # One credential per environment that holds a client of its own: its id is made from the connection and the
    # environment, so the update below finds the row the insert made.
    if dialect == "mssql":
        op.execute(
            "INSERT INTO app_credentials (tenant_id, id, team_id, app_id, client_id, secret_name, created_by, "
            "created_at, updated_by, updated_at) "
            "SELECT ce.tenant_id, CONCAT('cred_', ce.connection_id, '_', ce.environment), ce.team_id, "
            "COALESCE(c.plugin_id, ce.connection_id), JSON_VALUE(ce.settings, '$.clientId'), "
            "JSON_VALUE(ce.secrets, '$.clientSecret'), ce.updated_by, ce.updated_at, ce.updated_by, ce.updated_at "
            "FROM connection_environments ce JOIN connections c "
            "ON c.tenant_id = ce.tenant_id AND c.id = ce.connection_id "
            "WHERE JSON_VALUE(ce.settings, '$.clientId') IS NOT NULL AND ce.platform_app IS NULL"
        )
        op.execute(
            "UPDATE connection_environments SET credential_id = CONCAT('cred_', connection_id, '_', environment) "
            "WHERE JSON_VALUE(settings, '$.clientId') IS NOT NULL AND platform_app IS NULL"
        )
        op.execute(
            "UPDATE connection_environments SET settings = JSON_MODIFY(settings, '$.clientId', NULL), "
            "secrets = JSON_MODIFY(secrets, '$.clientSecret', NULL) "
            "WHERE JSON_VALUE(settings, '$.clientId') IS NOT NULL"
        )
    else:
        op.execute(
            "INSERT INTO app_credentials (tenant_id, id, team_id, app_id, client_id, secret_name, created_by, "
            "created_at, updated_by, updated_at) "
            "SELECT ce.tenant_id, 'cred_' || ce.connection_id || '_' || ce.environment, ce.team_id, "
            "COALESCE(c.plugin_id, ce.connection_id), json_extract_path_text(ce.settings, 'clientId'), "
            "json_extract_path_text(ce.secrets, 'clientSecret'), "
            "ce.updated_by, ce.updated_at, ce.updated_by, ce.updated_at "
            "FROM connection_environments ce JOIN connections c "
            "ON c.tenant_id = ce.tenant_id AND c.id = ce.connection_id "
            "WHERE json_extract_path_text(ce.settings, 'clientId') IS NOT NULL AND ce.platform_app IS NULL"
        )
        op.execute(
            "UPDATE connection_environments SET credential_id = 'cred_' || connection_id || '_' || environment "
            "WHERE json_extract_path_text(settings, 'clientId') IS NOT NULL AND platform_app IS NULL"
        )
        op.execute(
            "UPDATE connection_environments SET settings = (settings::jsonb - 'clientId')::json, "
            "secrets = (secrets::jsonb - 'clientSecret')::json "
            "WHERE json_extract_path_text(settings, 'clientId') IS NOT NULL"
        )
    op.drop_table("plugin_app_keys")
    table = _marked()
    if dialect == "postgresql":
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON app_credentials TO {ROLE}")
    elif dialect == "mssql":
        for statement in mssql_predicates_ddl(CHAIN, [table], column_type=_column_type, system_user=None):
            op.execute(statement)
    else:
        return
    for statement in isolation_ddl(table, dialect, chain=CHAIN):
        op.execute(statement)


def downgrade() -> None:
    dialect = op.get_context().dialect.name
    if dialect in ("postgresql", "mssql"):
        for statement in isolation_drop_ddl(_marked(), dialect):
            op.execute(statement)
    if dialect == "postgresql":
        op.execute("SET LOCAL row_security = off")
        op.execute(
            "UPDATE connection_environments ce SET settings = (ce.settings::jsonb || "
            "json_build_object('clientId', a.client_id)::jsonb)::json, secrets = (ce.secrets::jsonb || "
            "CASE WHEN a.secret_name IS NULL THEN '{}'::jsonb "
            "ELSE json_build_object('clientSecret', a.secret_name)::jsonb END)::json "
            "FROM app_credentials a WHERE a.tenant_id = ce.tenant_id AND a.id = ce.credential_id"
        )
    op.create_table(
        "plugin_app_keys",
        sa.Column("tenant_id", sa.String(64), primary_key=True),
        sa.Column("plugin_id", sa.String(120), primary_key=True),
        sa.Column("ciphertext", sa.Text, nullable=False),
        sa.Column("updated_by", sa.String(320), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
    )
    op.drop_column("connection_environments", "credential_id")
    op.drop_table("app_credentials")
