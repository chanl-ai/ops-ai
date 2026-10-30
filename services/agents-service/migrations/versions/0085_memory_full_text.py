"""A person's memories are searched by the database's full-text search (c-563)

Revision ID: 0085_memory_full_text
Revises: 0084_memory_audit_team_required

Matching scanned the newest rows with a substring test, so an old memory was never found and "plan" matched "airplane".
PostgreSQL now indexes each memory's key and value as a `simple` tsvector. SQL Server gets a full-text catalog and
index on the same columns only where the server has Full-Text Search installed; without it the store counts matching
words over every row instead, so no new install requirement is added. SQL Server builds full-text objects outside a
transaction. Runs on PostgreSQL and SQL Server.
"""

from __future__ import annotations

from alembic import op

revision = "0085_memory_full_text"
down_revision = "0084_memory_audit_team_required"
branch_labels = None
depends_on = None

# The same expression as ops_agents.store.memories.PG_DOCUMENT, which queries must use for the index to apply.
PG_DOCUMENT = "to_tsvector('simple', coalesce(key, '') || ' ' || value)"
CATALOG = "ops_memory"
# Only where the server has Full-Text Search installed. Also run by tests/store/test_memory_history.py on SQL Server.
MSSQL_FULL_TEXT = (
    "IF FULLTEXTSERVICEPROPERTY('IsFullTextInstalled') = 1 BEGIN "
    f"IF NOT EXISTS (SELECT 1 FROM sys.fulltext_catalogs WHERE name = '{CATALOG}') "
    f"EXEC('CREATE FULLTEXT CATALOG {CATALOG}'); "
    "IF NOT EXISTS (SELECT 1 FROM sys.fulltext_indexes WHERE object_id = OBJECT_ID('agent_memories')) "
    "EXEC('CREATE FULLTEXT INDEX ON agent_memories ([key], value) KEY INDEX agent_memories_pkey "
    f"ON {CATALOG} WITH CHANGE_TRACKING AUTO'); END"
)


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute(f"CREATE INDEX ix_agent_memories_text ON agent_memories USING gin ({PG_DOCUMENT})")
    elif dialect == "mssql":
        with op.get_context().autocommit_block():
            op.execute(MSSQL_FULL_TEXT)


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_agent_memories_text")
    elif dialect == "mssql":
        with op.get_context().autocommit_block():
            op.execute(
                "IF EXISTS (SELECT 1 FROM sys.fulltext_indexes WHERE object_id = OBJECT_ID('agent_memories')) "
                "DROP FULLTEXT INDEX ON agent_memories; "
                f"IF EXISTS (SELECT 1 FROM sys.fulltext_catalogs WHERE name = '{CATALOG}') "
                f"DROP FULLTEXT CATALOG {CATALOG}"
            )
