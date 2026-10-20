"""engine_definitions: team_id, and the tenant role may lock a version row (FOR UPDATE needs UPDATE)

Revision ID: 0028_engine_definitions_row_lock
Revises: 0027_engine_definitions_delete

A run start locks the version it pins and a workflow delete locks every version before it counts runs, so a run is
never pinned to a deleted version (ops_engine.store.runs and .definitions). Rows are still never updated. team_id
scopes the v2 list, read and delete to the owning team; null (seeded) rows are every team's.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0028_engine_definitions_row_lock"
down_revision = "0027_engine_definitions_delete"
branch_labels = None
depends_on = None

TENANT_ROLE = "ops_runtime_tenant"


def upgrade() -> None:
    with op.batch_alter_table("engine_definitions") as b:
        b.add_column(sa.Column("team_id", sa.String(64)))
    if op.get_bind().dialect.name == "postgresql":
        op.execute(f"GRANT UPDATE ON engine_definitions TO {TENANT_ROLE}")


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(f"REVOKE UPDATE ON engine_definitions FROM {TENANT_ROLE}")
    with op.batch_alter_table("engine_definitions") as b:
        b.drop_column("team_id")
