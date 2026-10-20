"""engine_definitions: stage, so only a reviewed version starts live runs (c-075)

Revision ID: 0031_engine_definitions_stage
Revises: 0030_chat_attachments

A version is a draft when saved, live once a publish request for it is approved, paused while its workflow is paused,
and superseded when a newer version goes live. Existing rows could all start runs before this column, so each
workflow's newest version is backfilled live and the older ones superseded; a backfill to draft would stop every
seeded workflow from starting.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0031_engine_definitions_stage"
down_revision = "0030_chat_attachments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("engine_definitions") as b:
        b.add_column(sa.Column("stage", sa.String(16), nullable=False, server_default="draft"))
    # Newest version per workflow, read first and written by key: MySQL refuses an UPDATE whose subquery reads the
    # table being updated (error 1093), so the backfill uses no such subquery.
    t = sa.table(
        "engine_definitions",
        sa.column("tenant_id", sa.String),
        sa.column("workflow_id", sa.String),
        sa.column("version", sa.Integer),
        sa.column("stage", sa.String),
    )
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # The table forces tenant row-level security; with it on, a role that does not bypass it would read no rows and
        # backfill nothing. Off, such a role fails the migration instead.
        op.execute("SET LOCAL row_security = off")
    newest = bind.execute(
        sa.select(t.c.tenant_id, t.c.workflow_id, sa.func.max(t.c.version)).group_by(t.c.tenant_id, t.c.workflow_id)
    ).all()
    for tenant, workflow, version in newest:
        mine = sa.and_(t.c.tenant_id == tenant, t.c.workflow_id == workflow)
        bind.execute(t.update().where(mine, t.c.version == version).values(stage="live"))
        bind.execute(t.update().where(mine, t.c.version < version).values(stage="superseded"))


def downgrade() -> None:
    with op.batch_alter_table("engine_definitions") as b:
        b.drop_column("stage")
