"""tenant egress allow-list: hosts, private ranges, audit, and module hosts as links into the list

Each module kept its own `egress_hosts` list. The tenant's allow-list replaces it: every host a module already
listed is added to its tenant's list (audited as added by this migration), each module's hosts become rows in
`module_egress_hosts` that must name a listed host, and the column goes.

Revision ID: tools_0004_egress
Revises: tools_0003_executor
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "tools_0004_egress"
down_revision = "tools_0003_executor"
branch_labels = None
depends_on = None

ACTOR = "migration tools_0004_egress"


def _listed(name: str, key: str, length: int) -> None:
    op.create_table(
        name,
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column(key, sa.String(length=length), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("added_by", sa.String(length=200), nullable=False),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", key),
    )


def upgrade() -> None:
    _listed("egress_hosts", "host", 253)
    _listed("egress_ranges", "cidr", 64)
    op.create_table(
        "egress_audit",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=8), nullable=False),
        sa.Column("value", sa.String(length=253), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("actor", sa.String(length=200), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_egress_audit_tenant_id"), "egress_audit", ["tenant_id"], unique=False)
    op.create_table(
        "module_egress_hosts",
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("module_id", sa.String(length=64), nullable=False),
        sa.Column("host", sa.String(length=253), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "host"], ["egress_hosts.tenant_id", "egress_hosts.host"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "module_id"], ["tool_modules.tenant_id", "tool_modules.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("tenant_id", "module_id", "host"),
    )
    # Every host a module listed joins its tenant's list, then each module links to it in its old order.
    op.execute(
        f"""
        INSERT INTO egress_hosts (tenant_id, host, note, added_by, added_at)
        SELECT DISTINCT m.tenant_id, h.host, 'listed by a module before the tenant allow-list', '{ACTOR}', now()
        FROM tool_modules m, json_array_elements_text(m.egress_hosts) AS h(host)
        """
    )
    op.execute(
        f"""
        INSERT INTO egress_audit (tenant_id, kind, value, action, actor, at)
        SELECT tenant_id, 'host', host, 'added', '{ACTOR}', added_at FROM egress_hosts
        """
    )
    op.execute(
        """
        INSERT INTO module_egress_hosts (tenant_id, module_id, host, position)
        SELECT DISTINCT ON (m.tenant_id, m.id, h.host) m.tenant_id, m.id, h.host, h.n - 1
        FROM tool_modules m, json_array_elements_text(m.egress_hosts) WITH ORDINALITY AS h(host, n)
        ORDER BY m.tenant_id, m.id, h.host, h.n
        """
    )
    op.drop_column("tool_modules", "egress_hosts")


def downgrade() -> None:
    op.add_column("tool_modules", sa.Column("egress_hosts", sa.JSON(), nullable=False, server_default="[]"))
    op.execute(
        """
        UPDATE tool_modules m SET egress_hosts = coalesce(
            (SELECT json_agg(l.host ORDER BY l.position) FROM module_egress_hosts l
             WHERE l.tenant_id = m.tenant_id AND l.module_id = m.id), '[]'::json)
        """
    )
    op.drop_table("module_egress_hosts")
    op.drop_index(op.f("ix_egress_audit_tenant_id"), table_name="egress_audit")
    op.drop_table("egress_audit")
    op.drop_table("egress_ranges")
    op.drop_table("egress_hosts")
