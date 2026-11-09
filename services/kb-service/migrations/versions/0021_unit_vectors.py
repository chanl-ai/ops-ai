"""Index units keep a vector, for search by meaning

kb_unit_vectors holds each index unit's embedding with the model and width it was made with, so a change of the
environment's embedding model embeds every unit again and reads nothing again. On PostgreSQL the vectors live in
pgvector, which this revision requires: `CREATE EXTENSION vector` needs a superuser, so a database installed by a DBA
has it created by the DBA first (docs/deploy/database.md), and IF NOT EXISTS then changes nothing. An HNSW index serves
the environment's width (OPS_EMBEDDING_WIDTH). SQL Server and SQLite get no vector table yet (decision D17), and
kb-service searches there on keywords only, saying so in each result.

Bases made while keyword search was the only one stored searchMode "keyword" as a default, not a choice; they search
both lanes from now on, as a new base does. Every statement renders offline, so an upgrade bundle can carry it.

Revision ID: kb_0021
Revises: kb_0020
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from ops_service_kit.settings import Settings
from ops_store.dialect import Vector, vector_index_ddl
from ops_store.schema import TEAM_OWNED, TENANT_SCOPED, isolation_ddl, isolation_drop_ddl

revision = "kb_0021"
down_revision = "kb_0020"
branch_labels = None
depends_on = None

CHAIN = "kb"
ROLE = "ops_kb_tenant"
TABLE = "kb_unit_vectors"
# The stored default before meaning search, moved to both lanes; per database, as JSON is edited differently in each.
HYBRID = {
    "postgresql": "UPDATE kb_bases SET retrieval = jsonb_set(retrieval::jsonb, '{searchMode}', '\"hybrid\"')::json "
    "WHERE retrieval->>'searchMode' = 'keyword'",
    "mssql": "UPDATE kb_bases SET retrieval = JSON_MODIFY(retrieval, '$.searchMode', 'hybrid') "
    "WHERE JSON_VALUE(retrieval, '$.searchMode') = 'keyword'",
    "sqlite": "UPDATE kb_bases SET retrieval = json_set(retrieval, '$.searchMode', 'hybrid') "
    "WHERE json_extract(retrieval, '$.searchMode') = 'keyword'",
}


def _marked() -> sa.Table:
    return sa.Table(
        TABLE,
        sa.MetaData(),
        sa.Column("tenant_id", sa.String(64)),
        sa.Column("team_id", sa.String(64)),
        info={**TENANT_SCOPED, **TEAM_OWNED},
    )


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect in HYBRID:
        if dialect == "postgresql":
            # The migrate login moves every tenant's bases, past the tenant policy.
            op.execute("SET LOCAL row_security = off")
        op.execute(HYBRID[dialect])
    if dialect != "postgresql":
        return
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        TABLE,
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("team_id", sa.String(64), nullable=False),
        sa.Column("unit_id", sa.String(64), nullable=False),
        sa.Column("chunk_id", sa.String(64), nullable=False),
        sa.Column("item_id", sa.String(64), nullable=False),
        sa.Column("model", sa.String(120), nullable=False),
        sa.Column("width", sa.Integer, nullable=False),
        sa.Column("embedding", Vector(), nullable=False),
        sa.Column("embedded_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "unit_id"],
            ["kb_units.tenant_id", "kb_units.id"],
            ondelete="CASCADE",
            name="fk_kb_vector_unit",
        ),
        sa.PrimaryKeyConstraint("tenant_id", "unit_id"),
    )
    op.create_index("ix_kb_unit_vectors_chunk", TABLE, ["tenant_id", "chunk_id"])
    ddl = vector_index_ddl("postgresql", TABLE, "embedding", Settings().embedding_width)
    if ddl:
        op.execute(ddl)
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {TABLE} TO {ROLE}")
    for statement in isolation_ddl(_marked(), "postgresql", chain=CHAIN):
        op.execute(statement)


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for statement in isolation_drop_ddl(_marked(), "postgresql"):
        op.execute(statement)
    op.drop_table(TABLE)
