"""agent_memories and memory_audit: what an agent remembers about each person (c-124)

Revision ID: 0048_agent_memories
Revises: 0047_mailboxes

One row per memory, keyed by the person (the token's subject) and the agent, never by conversation. A fact or
preference has a key; a newer value for the same key supersedes the older row (`superseded_at`), which stays for the
record and is not loaded. An episode is a short summary with no key. A forget deletes the row and writes an audit row.
Tenant RLS as on team_default_agents (0044).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0048_agent_memories"
down_revision = "0047_mailboxes"
branch_labels = None
depends_on = None

TENANT_ROLE = "ops_runtime_tenant"


def upgrade() -> None:
    op.create_table(
        "agent_memories",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False, index=True),
        sa.Column("team_id", sa.String(64), nullable=False),
        sa.Column("agent_id", sa.String(64), nullable=False),
        sa.Column("person", sa.String(320), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("key", sa.String(120)),
        sa.Column("value", sa.String(2000), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("source_thread_id", sa.String(64)),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("superseded_at", sa.String(32)),
    )
    op.create_index("ix_agent_memories_owner", "agent_memories", ["tenant_id", "person", "agent_id"])
    op.create_table(
        "memory_audit",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False, index=True),
        sa.Column("person", sa.String(320), nullable=False),
        sa.Column("agent_id", sa.String(64), nullable=False),
        sa.Column("memory_id", sa.String(64)),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("actor", sa.String(320), nullable=False),
        sa.Column("at", sa.String(32), nullable=False),
    )
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(f"DO $$ BEGIN CREATE ROLE {TENANT_ROLE} NOLOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END $$")
    for table in ("agent_memories", "memory_audit"):
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO {TENANT_ROLE}")
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {table}_tenant ON {table} "
            "USING (tenant_id = current_setting('app.tenant_id', true)) "
            "WITH CHECK (tenant_id = current_setting('app.tenant_id', true))"
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        for table in ("agent_memories", "memory_audit"):
            op.execute(f"DROP POLICY IF EXISTS {table}_tenant ON {table}")
    op.drop_table("memory_audit")
    op.drop_index("ix_agent_memories_owner", table_name="agent_memories")
    op.drop_table("agent_memories")
