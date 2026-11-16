"""store_roles: the grants every store transaction needs, and a system role for the loops that read every tenant

Every tools store now runs its statements as ops_tools_tenant (`Store.tx()`), so that role writes the module registry
it only read before (tools_0044). The start-up catch-up of team defaults, the review hand-over and the sign-in
keep-alive list the teams and records they then work one tenant at a time; that listing runs as ops_tools_system, a
role row-level security does not apply to, whose grants are only the reads those listings make, the relay's marks on
the outbox and the retention sweep's deletes of old secret use rows. PostgreSQL only: on
SQL Server the runtime user holds every grant (deploy/database/golden/mssql/grants.sql).

Revision ID: tools_0081_store_roles
Revises: tools_0080_police_tables
"""

from __future__ import annotations

from alembic import op

from ops_store.schema import member_ddl, role_ddl

revision = "tools_0081_store_roles"
down_revision = "tools_0080_police_tables"
branch_labels = None
depends_on = None

ROLE = "ops_tools_tenant"
SYSTEM_ROLE = "ops_tools_system"
LOGIN = "ops_tools_runtime"
# What the tenant role may now do that it could not: write the registry (it held SELECT on tool_modules, tools_0044).
TENANT_GRANTS = {"tool_modules": "SELECT, INSERT, UPDATE, DELETE"}
# What a listing across tenants reads; nothing else.
SYSTEM_READS = ("team_defaults", "tool_modules", "module_versions", "module_approvals", "module_operations")
# What the system role changes: the relay marks and prunes every tenant's events, the retention sweep deletes secret
# use rows past their age.
SYSTEM_WRITES = {"service_outbox": "SELECT, UPDATE, DELETE", "secret_audit": "SELECT, DELETE"}


def upgrade() -> None:
    if op.get_context().dialect.name != "postgresql":
        return
    for name, grant in TENANT_GRANTS.items():
        op.execute(f"GRANT {grant} ON {name} TO {ROLE}")
    op.execute(role_ddl(SYSTEM_ROLE, bypass=True))
    for name in SYSTEM_READS:
        op.execute(f"GRANT SELECT ON {name} TO {SYSTEM_ROLE}")
    for name, grant in SYSTEM_WRITES.items():
        op.execute(f"GRANT {grant} ON {name} TO {SYSTEM_ROLE}")
    op.execute(member_ddl(SYSTEM_ROLE, LOGIN))


def downgrade() -> None:
    if op.get_context().dialect.name != "postgresql":
        return
    for name in (*SYSTEM_READS, *SYSTEM_WRITES):
        op.execute(f"REVOKE ALL ON {name} FROM {SYSTEM_ROLE}")
    for name in TENANT_GRANTS:
        op.execute(f"REVOKE INSERT, UPDATE, DELETE ON {name} FROM {ROLE}")
