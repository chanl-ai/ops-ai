"""registry_publish_requests per tenant, with tenant row-level security (c-333 phase A)

Revision ID: 0067_publish_requests_tenant
Revises: 0066_engine_runs_list_indexes

Publish requests were one list for every tenant: a request one tenant opened blocked another's for the same subject id
(every tenant has the same seeded workflows), and Reviews listed them all. Each row now carries its tenant (existing
rows are the dev tenant, "local", as in 0021), the id is unique per tenant, and on PostgreSQL the table gets the run
tables' policy (0021): a row is visible and writable only while `app.tenant_id` names its tenant.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0067_publish_requests_tenant"
down_revision = "0066_engine_runs_list_indexes"
branch_labels = None
depends_on = None

TABLE = "registry_publish_requests"
TENANT_ROLE = "ops_runtime_tenant"


def upgrade() -> None:
    with op.batch_alter_table(TABLE) as b:
        b.add_column(sa.Column("tenant_id", sa.String(64), nullable=False, server_default="local"))
    op.create_index(f"ix_{TABLE}_tenant_id", TABLE, ["tenant_id"])
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(f"ALTER TABLE {TABLE} DROP CONSTRAINT {TABLE}_pkey")
    op.execute(f"ALTER TABLE {TABLE} ADD PRIMARY KEY (tenant_id, id)")
    # Roles are cluster-wide, so another database on the same server may already have created it.
    op.execute(f"DO $$ BEGIN CREATE ROLE {TENANT_ROLE} NOLOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END $$")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {TABLE} TO {TENANT_ROLE}")
    op.execute(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY")
    # An unset app.tenant_id reads as NULL, which matches no row: a statement without a tenant sees nothing.
    op.execute(
        f"CREATE POLICY {TABLE}_tenant ON {TABLE} "
        "USING (tenant_id = current_setting('app.tenant_id', true)) "
        "WITH CHECK (tenant_id = current_setting('app.tenant_id', true))"
    )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(f"DROP POLICY IF EXISTS {TABLE}_tenant ON {TABLE}")
        op.execute(f"ALTER TABLE {TABLE} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {TABLE} DISABLE ROW LEVEL SECURITY")
        op.execute(f"REVOKE ALL ON {TABLE} FROM {TENANT_ROLE}")
        op.execute(f"ALTER TABLE {TABLE} DROP CONSTRAINT {TABLE}_pkey")
        # Ids repeat across tenants: every row is kept, the dev tenant's under its own id, the others' prefixed with
        # their tenant so the id alone is unique again.
        op.execute(f"UPDATE {TABLE} SET id = left(tenant_id || ':' || id, 64) WHERE tenant_id <> 'local'")
        op.execute(f"ALTER TABLE {TABLE} ADD PRIMARY KEY (id)")
    op.drop_index(f"ix_{TABLE}_tenant_id", table_name=TABLE)
    with op.batch_alter_table(TABLE) as b:
        b.drop_column("tenant_id")
