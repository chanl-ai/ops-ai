"""agent_memories: the system role reads the tenant column, for the retention sweep (c-124)

Revision ID: 0072_memories_system_tenants
Revises: 0071_hot_query_indexes

The retention sweep starts before it knows a tenant, so it lists the tenants holding memories as ops_runtime_system,
which bypasses row-level security (Memories.tenants), then expires each tenant's under its own. 0048 granted the table
to the tenant role alone, so every pass was refused and no memory expired. The grant is the tenant_id column only: the
bypass role never reads what an agent remembers about a person.
"""

from __future__ import annotations

from alembic import op

revision = "0072_memories_system_tenants"
down_revision = "0071_hot_query_indexes"
branch_labels = None
depends_on = None

SYSTEM_ROLE = "ops_runtime_system"


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(
        f"DO $$ BEGIN CREATE ROLE {SYSTEM_ROLE} NOLOGIN BYPASSRLS; EXCEPTION WHEN duplicate_object THEN NULL; END $$"
    )
    op.execute(f"GRANT SELECT (tenant_id) ON agent_memories TO {SYSTEM_ROLE}")


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(f"REVOKE SELECT (tenant_id) ON agent_memories FROM {SYSTEM_ROLE}")
