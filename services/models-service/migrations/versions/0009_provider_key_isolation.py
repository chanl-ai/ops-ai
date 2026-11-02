"""provider_key_isolation: an account's model provider keys are held to their tenant by the database (c-616 C3)

provider_keys was filtered only by the tenant clause its store wrote: nothing in the database stopped a query that
left the clause out from reading another account's sealed keys. It now carries the generated tenant policy
(ops_store.schema.isolation_ddl) for ops_models_tenant, the role every provider key transaction runs as, and the
service's runtime login becomes a member of it, as tools' saved sign-ins are held (tools_0044). provider_connections
names no tenant and holds no value (an install's connection, 10-27): it stays an install table, its DML the runtime
login's alone.

Revision ID: models_0009
Revises: models_0008
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mssql

from ops_store.schema import (
    TENANT_SCOPED,
    isolation_ddl,
    isolation_drop_ddl,
    member_ddl,
    mssql_predicates_ddl,
    role_ddl,
)

revision = "models_0009"
down_revision = "models_0008"
branch_labels = None
depends_on = None

CHAIN = "models"
ROLE = "ops_models_tenant"
LOGIN = "ops_models_runtime"


def _keys() -> sa.Table:
    return sa.Table("provider_keys", sa.MetaData(), sa.Column("tenant_id", sa.String(64)), info=TENANT_SCOPED)


def _column_type(column: sa.Column[Any]) -> str:
    return column.type.compile(dialect=mssql.dialect())


def upgrade() -> None:
    dialect = op.get_context().dialect.name
    if dialect == "postgresql":
        # The migrating role may own the table; once FORCE is on, row-level security would hide rows from it.
        op.execute("SET LOCAL row_security = off")
        op.execute(role_ddl(ROLE))
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON provider_keys TO {ROLE}")
        op.execute(member_ddl(ROLE, LOGIN))
    elif dialect == "mssql":
        for statement in mssql_predicates_ddl(CHAIN, [_keys()], column_type=_column_type, system_user=None):
            op.execute(statement)
    else:
        return
    for statement in isolation_ddl(_keys(), dialect, chain=CHAIN):
        op.execute(statement)


def downgrade() -> None:
    dialect = op.get_context().dialect.name
    if dialect not in ("postgresql", "mssql"):
        return
    for statement in isolation_drop_ddl(_keys(), dialect):
        op.execute(statement)
    if dialect == "postgresql":
        op.execute(f"REVOKE ALL ON provider_keys FROM {ROLE}")
