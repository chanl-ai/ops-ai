"""ops_runtime_system reads each agent's tenant, id and published pointer: the start-up serving reload

At start agents-service serves every tenant's published, unpaused agents before any request names a tenant. It finds
them as the BYPASSRLS role, as the Ops Assistant catch-up finds its teams (0096), then reads each tenant's specs under
that tenant. The grant is four columns only: the role never reads an agent's name, slug or spec. SQL Server's system
user holds the same columns (deploy/database/mssql.py SYSTEM_READS).

Revision ID: 0107_system_reads_agent_pointers
Revises: 0106_registry_tenant_columns
"""

from __future__ import annotations

from alembic import op

revision = "0107_system_reads_agent_pointers"
down_revision = "0106_registry_tenant_columns"
branch_labels = None
depends_on = None

SYSTEM_ROLE = "ops_runtime_system"
COLUMNS = "tenant_id, id, published_version, paused"


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(f"GRANT SELECT ({COLUMNS}) ON registry_agents TO {SYSTEM_ROLE}")


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(f"REVOKE SELECT ({COLUMNS}) ON registry_agents FROM {SYSTEM_ROLE}")
