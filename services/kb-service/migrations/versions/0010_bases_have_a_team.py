"""Every knowledge base and source belongs to one team (c-507)

Revision ID: kb_0010
Revises: kb_0009

A base or source with no team was read by every team. Each now must have one. A base an agent cites is copied into
each citing team only by moving the agent's citation, which lives in agents-service's tables, so this migration does
not guess: it refuses while any row has no team and names each one to be placed first. Runs on PostgreSQL and SQL
Server.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import context, op

revision = "kb_0010"
down_revision = "kb_0009"
branch_labels = None
depends_on = None

TABLES = ("kb_bases", "kb_sources")


def upgrade() -> None:
    bind = op.get_bind()
    if not context.is_offline_mode():
        left: list[str] = []
        for name in TABLES:
            t = sa.table(name, sa.column("tenant_id"), sa.column("id"), sa.column("team_id"))
            rows = bind.execute(sa.select(t.c.tenant_id, t.c.id).where(t.c.team_id.is_(None))).all()
            left += [f"{name} {row_id} of {tenant}" for tenant, row_id in rows]
        if left:
            raise RuntimeError(f"rows with no team: {', '.join(left)}; give each the team that uses it first")
    for name in TABLES:
        with op.batch_alter_table(name) as b:
            b.alter_column("team_id", existing_type=sa.String(64), nullable=False)


def downgrade() -> None:
    for name in reversed(TABLES):
        with op.batch_alter_table(name) as b:
            b.alter_column("team_id", existing_type=sa.String(64), nullable=True)
