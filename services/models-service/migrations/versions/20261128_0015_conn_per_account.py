"""Each model provider connection and alias is an account's own, held to its tenant by the database

provider_connections and model_aliases were install tables: every account listed, read and re-pointed every
connection, so one account could move another's connection to an endpoint of its own and receive that account's
provider key with its next call, and every account shared one `default` chat alias. Both now carry `tenant_id` (a
connection name, and an alias name, unique within its account) and the generated tenant policy for ops_models_tenant
(models_0009), which every connection and alias transaction runs as. Ops AI holds no connection that must be kept: the
rows are deleted, and the dev seed or an account admin makes them again.

Revision ID: 20261128_0015_conn_per_account
Revises: 20261122_2017_list_sort_indexes
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mssql

from ops_store.schema import TENANT_SCOPED, isolation_ddl, isolation_drop_ddl, mssql_predicates_ddl

revision = "20261128_0015_conn_per_account"
down_revision = "20261122_2017_list_sort_indexes"
branch_labels = None
depends_on = None

CHAIN = "models"
ROLE = "ops_models_tenant"
UNIQUE = "uq_provider_connections_tenant_name"
CURRENT = "ux_model_aliases_current"
WHERE = sa.text("status = 'current'")


def _tables() -> list[sa.Table]:
    md = sa.MetaData()
    return [
        sa.Table(name, md, sa.Column("tenant_id", sa.String(64)), info=TENANT_SCOPED)
        for name in ("provider_connections", "model_aliases")
    ]


def _column_type(column: sa.Column[Any]) -> str:
    return column.type.compile(dialect=mssql.dialect())


def upgrade() -> None:
    dialect = op.get_context().dialect.name
    # A connection with no tenant has no account to be held to; the aliases bound to them go with them.
    op.execute("DELETE FROM model_aliases")
    op.execute("DELETE FROM provider_connections")
    op.drop_constraint("provider_connections_name_key", "provider_connections", type_="unique")
    op.add_column("provider_connections", sa.Column("tenant_id", sa.String(64), nullable=False))
    op.create_unique_constraint(UNIQUE, "provider_connections", ["tenant_id", "name"])
    op.drop_index(CURRENT, table_name="model_aliases")
    op.drop_constraint("model_aliases_pkey", "model_aliases", type_="primary")
    op.add_column("model_aliases", sa.Column("tenant_id", sa.String(64), nullable=False))
    op.create_primary_key("model_aliases_pkey", "model_aliases", ["tenant_id", "name", "version"])
    op.create_index(
        CURRENT, "model_aliases", ["tenant_id", "name"], unique=True, postgresql_where=WHERE, mssql_where=WHERE
    )
    if dialect == "postgresql":
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON provider_connections TO {ROLE}")
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON model_aliases TO {ROLE}")
    elif dialect == "mssql":
        for statement in mssql_predicates_ddl(CHAIN, _tables(), column_type=_column_type, system_user=None):
            op.execute(statement)
    else:
        return
    for table in _tables():
        for statement in isolation_ddl(table, dialect, chain=CHAIN):
            op.execute(statement)


def downgrade() -> None:
    dialect = op.get_context().dialect.name
    if dialect in ("postgresql", "mssql"):
        for table in _tables():
            for statement in isolation_drop_ddl(table, dialect):
                op.execute(statement)
    if dialect == "postgresql":
        op.execute(f"REVOKE ALL ON model_aliases FROM {ROLE}")
        op.execute(f"REVOKE ALL ON provider_connections FROM {ROLE}")
    # Two accounts may hold one name, which the install-wide unique name refuses.
    op.execute("DELETE FROM model_aliases")
    op.execute("DELETE FROM provider_connections")
    op.drop_index(CURRENT, table_name="model_aliases")
    op.drop_constraint("model_aliases_pkey", "model_aliases", type_="primary")
    op.drop_column("model_aliases", "tenant_id")
    op.create_primary_key("model_aliases_pkey", "model_aliases", ["name", "version"])
    op.create_index(CURRENT, "model_aliases", ["name"], unique=True, postgresql_where=WHERE, mssql_where=WHERE)
    op.drop_constraint(UNIQUE, "provider_connections", type_="unique")
    op.drop_column("provider_connections", "tenant_id")
    op.create_unique_constraint("provider_connections_name_key", "provider_connections", ["name"])
