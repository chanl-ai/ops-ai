"""model_key_tenant_isolation: each tenant's share of a per-tenant model key is held to that tenant (c-616 C4)

model_key_tenants was filtered only by the tenant the completion route passed its store: nothing in the database
stopped a query that left it out from reading or spending another tenant's share. It now carries the generated tenant
policy for ops_models_tenant (models_0009), which a per-tenant call's share and spend run as; the spend moves the
key's own total in the same transaction, so the role may update model_keys too. model_keys names no tenant (one
identity's key, used for many tenants, 10-27): it stays an install table.

Revision ID: models_0010
Revises: models_0009
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mssql

from ops_store.schema import TENANT_SCOPED, isolation_ddl, isolation_drop_ddl, mssql_predicates_ddl

revision = "models_0010"
down_revision = "models_0009"
branch_labels = None
depends_on = None

CHAIN = "models"
ROLE = "ops_models_tenant"


def _shares() -> sa.Table:
    return sa.Table("model_key_tenants", sa.MetaData(), sa.Column("tenant_id", sa.String(64)), info=TENANT_SCOPED)


def _column_type(column: sa.Column[Any]) -> str:
    return column.type.compile(dialect=mssql.dialect())


def upgrade() -> None:
    dialect = op.get_context().dialect.name
    if dialect == "postgresql":
        op.execute("SET LOCAL row_security = off")
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON model_key_tenants TO {ROLE}")
        op.execute(f"GRANT SELECT, UPDATE ON model_keys TO {ROLE}")
    elif dialect == "mssql":
        for statement in mssql_predicates_ddl(CHAIN, [_shares()], column_type=_column_type, system_user=None):
            op.execute(statement)
    else:
        return
    for statement in isolation_ddl(_shares(), dialect, chain=CHAIN):
        op.execute(statement)


def downgrade() -> None:
    dialect = op.get_context().dialect.name
    if dialect not in ("postgresql", "mssql"):
        return
    for statement in isolation_drop_ddl(_shares(), dialect):
        op.execute(statement)
    if dialect == "postgresql":
        op.execute(f"REVOKE ALL ON model_key_tenants FROM {ROLE}")
        op.execute(f"REVOKE ALL ON model_keys FROM {ROLE}")
