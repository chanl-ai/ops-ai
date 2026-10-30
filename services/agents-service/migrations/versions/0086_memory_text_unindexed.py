"""PostgreSQL ranks memories without a full-text index (c-563)

Revision ID: 0086_memory_text_unindexed
Revises: 0085_memory_full_text

0085's GIN expression index cannot be held equal between the store's metadata and the migrated schema (PostgreSQL
rewrites the expression it stores), and it is not needed: every memory query first narrows to one person's memories by
ix_agent_memories_owner, and ranking those rows reads them directly. SQL Server keeps its full-text index where the
server has Full-Text Search, since CONTAINSTABLE needs one. Runs on PostgreSQL and SQL Server.
"""

from __future__ import annotations

from alembic import op

revision = "0086_memory_text_unindexed"
down_revision = "0085_memory_full_text"
branch_labels = None
depends_on = None

PG_DOCUMENT = "to_tsvector('simple', coalesce(key, '') || ' ' || value)"


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_agent_memories_text")


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(f"CREATE INDEX ix_agent_memories_text ON agent_memories USING gin ({PG_DOCUMENT})")
