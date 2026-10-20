"""engine_definitions: the runtime may delete a draft

Revision ID: 0027_engine_definitions_delete
Revises: 0026_skills

DELETE /v1/workflows/definitions/{id} removes a workflow that has never run (every version). Versions stay immutable:
there is still no UPDATE grant, and the route refuses a workflow with runs in the same transaction as the delete.
"""

from __future__ import annotations

from alembic import op

revision = "0027_engine_definitions_delete"
down_revision = "0026_skills"
branch_labels = None
depends_on = None

TENANT_ROLE = "ops_runtime_tenant"


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(f"GRANT DELETE ON engine_definitions TO {TENANT_ROLE}")


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(f"REVOKE DELETE ON engine_definitions FROM {TENANT_ROLE}")
