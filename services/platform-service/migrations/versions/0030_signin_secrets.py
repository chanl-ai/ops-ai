"""signin_secrets: the client secrets a workspace's sign-in providers name, kept by the workspace

A provider's `clientSecretRef` named a value in the install's OPS_SIGNIN_SECRETS setting, so one setting held every
workspace's secrets. Each workspace now saves its own here, sealed under the install's secrets key, under the same
row-level security as 0001.

Revision ID: 0030_signin_secrets
Revises: 0029_tenant_security_team
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from ops_store.schema import TENANT_SCOPED, isolation_ddl, isolation_drop_ddl

revision = "0030_signin_secrets"
down_revision = "0029_tenant_security_team"
branch_labels = None
depends_on = None

TENANT = "ops_platform_tenant"


def _named(column: str) -> str | None:
    """SQL Server names an unnamed key at random; there it takes PostgreSQL's name, as the golden DDL does."""
    return f"signin_secrets_{column}_fkey" if op.get_bind().dialect.name == "mssql" else None


def _sql_server_policy(*, create: bool) -> None:
    """SQL Server: the table's security policy over the chain's predicate functions, which the SQL Server bundle
    installed, made on the way up and dropped before the table on the way down (a policy is schema-bound to its
    table, so DROP TABLE is refused while it stands)."""
    if op.get_bind().dialect.name != "mssql":
        return
    table = sa.Table("signin_secrets", sa.MetaData(), sa.Column("tenant_id", sa.String(64)), info=TENANT_SCOPED)
    for statement in isolation_ddl(table, "mssql", chain="platform") if create else isolation_drop_ddl(table, "mssql"):
        op.execute(statement)


def upgrade() -> None:
    op.create_table(
        "signin_secrets",
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id", name=_named("tenant_id")), primary_key=True),
        sa.Column("name", sa.String(100), primary_key=True),
        sa.Column("ciphertext", sa.Text, nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("created_by", sa.String(64), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("rotated_at", sa.String(40)),
    )
    _sql_server_policy(create=True)
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON signin_secrets TO {TENANT}")
    op.execute("ALTER TABLE signin_secrets ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE signin_secrets FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY signin_secrets_tenant ON signin_secrets "
        "USING (tenant_id = current_setting('app.tenant_id', true)) "
        "WITH CHECK (tenant_id = current_setting('app.tenant_id', true))"
    )


def downgrade() -> None:
    _sql_server_policy(create=False)
    op.drop_table("signin_secrets")
