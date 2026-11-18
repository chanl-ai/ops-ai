"""system_reads_columns: the role that reads across tenants reads only the columns its listings name

tools_0081 granted ops_tools_system whole rows of the module registry, its versions, its approvals and its operations,
and a tool's headers, a module's sign-in and saved baseline can hold a credential. Its grants are now the columns each
listing reads: a module's tenant, id, team and name (the review hand-over), a version's tenant, module, number, review
and publisher with its status, an open request's event fields, and a team's defaults version. The start-up move of
sign-in header keys lists the tenants holding a team module and reads each tenant's headers in that tenant, so the
role reads no operation at all. PostgreSQL only: on SQL Server the system user is made and granted by
deploy/database/golden/mssql/grants.sql (deploy/database/mssql.py SYSTEM_USERS). Downgrade gives back whole rows.

Revision ID: tools_0083_system_reads_columns
Revises: tools_0082_tenant_fences
"""

from __future__ import annotations

from alembic import op

revision = "tools_0083_system_reads_columns"
down_revision = "tools_0082_tenant_fences"
branch_labels = None
depends_on = None

SYSTEM_ROLE = "ops_tools_system"
COLUMNS = {
    "tool_modules": ("tenant_id", "id", "team_id", "display_name"),
    "module_versions": ("tenant_id", "module_id", "version", "status", "review_id", "published_by"),
    "module_approvals": (
        "tenant_id",
        "module_id",
        "id",
        "status",
        "review_id",
        "decider_team",
        "workflow_id",
        "workflow_name",
        "operations",
        "environment",
        "expires_at",
        "justification",
        "requested_by",
        "requested_by_email",
    ),
    "team_defaults": ("tenant_id", "team_id", "version"),
}
# Whole-row reads tools_0081 granted; module_operations is read by no listing now.
WHOLE = (*COLUMNS, "module_operations")


def upgrade() -> None:
    if op.get_context().dialect.name != "postgresql":
        return
    for name in WHOLE:
        op.execute(f"REVOKE SELECT ON {name} FROM {SYSTEM_ROLE}")
    for name, columns in COLUMNS.items():
        op.execute(f"GRANT SELECT ({', '.join(columns)}) ON {name} TO {SYSTEM_ROLE}")


def downgrade() -> None:
    if op.get_context().dialect.name != "postgresql":
        return
    for name, columns in COLUMNS.items():
        op.execute(f"REVOKE SELECT ({', '.join(columns)}) ON {name} FROM {SYSTEM_ROLE}")
    for name in WHOLE:
        op.execute(f"GRANT SELECT ON {name} TO {SYSTEM_ROLE}")
