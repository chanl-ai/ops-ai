"""What is searched is kept apart from what is cited

kb_units holds every index unit of a piece: the piece itself, its smaller children, and the questions written for it,
each pointing at the piece (kb_chunks) a match returns and cites. Full-text search moves from kb_chunks onto kb_units;
each live chunk becomes its own unit, so search finds what it found before. A piece keeps the metadata its source maps
onto it. The units take their piece's team and the generated team policy. Search is PostgreSQL full text, so this chain
runs search on PostgreSQL; SQL Server gets the table and its policy without the text index.

Revision ID: kb_0016
Revises: kb_0015
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mssql, postgresql

from ops_store.schema import TEAM_OWNED, TENANT_SCOPED, isolation_ddl, isolation_drop_ddl, mssql_predicates_ddl

revision = "kb_0016"
down_revision = "kb_0015"
branch_labels = None
depends_on = None

CHAIN = "kb"
ROLE = "ops_kb_tenant"
TABLE = "kb_units"
TSV = "setweight(to_tsvector('english', coalesce(heading, '')), 'A') || setweight(to_tsvector('english', text), 'B')"
CHUNK_TSV = (
    "setweight(to_tsvector('english', coalesce(title, '') || ' ' || coalesce(section, '')), 'A')"
    " || setweight(to_tsvector('english', text), 'B')"
)


def _marked() -> sa.Table:
    return sa.Table(
        TABLE,
        sa.MetaData(),
        sa.Column("tenant_id", sa.String(64)),
        sa.Column("team_id", sa.String(64)),
        info={**TENANT_SCOPED, **TEAM_OWNED},
    )


def _column_type(column: sa.Column[Any]) -> str:
    return column.type.compile(dialect=mssql.dialect())


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    pg = dialect == "postgresql"
    if pg:
        op.execute("SET LOCAL row_security = off")
    columns: list[Any] = [
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("team_id", sa.String(64), nullable=False),
        sa.Column("id", sa.String(64), nullable=False),
        sa.Column("chunk_id", sa.String(64), nullable=False),
        sa.Column("item_id", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("position", sa.Integer, nullable=False),
        sa.Column("heading", sa.String(800), nullable=False),
        sa.Column("text", sa.Text, nullable=False),
    ]
    if pg:
        columns.append(sa.Column("tsv", postgresql.TSVECTOR(), sa.Computed(TSV, persisted=True)))
    op.create_table(
        TABLE,
        *columns,
        sa.ForeignKeyConstraint(
            ["tenant_id", "chunk_id"],
            ["kb_chunks.tenant_id", "kb_chunks.id"],
            ondelete="CASCADE",
            name="fk_kb_unit_chunk",
        ),
        sa.PrimaryKeyConstraint("tenant_id", "id"),
    )
    op.create_index("ix_kb_units_chunk", TABLE, ["tenant_id", "chunk_id"])
    if pg:
        op.execute("CREATE INDEX ix_kb_units_tsv ON kb_units USING gin (tsv)")
    op.add_column("kb_chunks", sa.Column("metadata", sa.JSON(), nullable=True))
    chunks = sa.table(
        "kb_chunks",
        sa.column("tenant_id", sa.String),
        sa.column("team_id", sa.String),
        sa.column("id", sa.String),
        sa.column("item_id", sa.String),
        sa.column("title", sa.String),
        sa.column("section", sa.String),
        sa.column("text", sa.Text),
        sa.column("withdrawn_at", sa.DateTime),
    )
    heading = chunks.c.title + sa.literal(" ") + chunks.c.section
    copied = sa.select(
        chunks.c.tenant_id,
        chunks.c.team_id,
        sa.literal("unt_") + chunks.c.id,
        chunks.c.id,
        chunks.c.item_id,
        sa.literal("self"),
        sa.literal(0),
        heading,
        chunks.c.text,
    ).where(chunks.c.withdrawn_at.is_(None))
    names = ["tenant_id", "team_id", "id", "chunk_id", "item_id", "kind", "position", "heading", "text"]
    units = sa.table(TABLE, *(sa.column(n, sa.String) for n in names))
    op.execute(units.insert().from_select(names, copied))
    if pg:
        op.execute("DROP INDEX IF EXISTS ix_kb_chunks_tsv")
        op.drop_column("kb_chunks", "tsv")
    if dialect == "mssql":
        for statement in mssql_predicates_ddl(CHAIN, [_marked()], column_type=_column_type, system_user=None):
            op.execute(statement)
    if dialect not in ("postgresql", "mssql"):
        return
    if pg:
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {TABLE} TO {ROLE}")
    for statement in isolation_ddl(_marked(), dialect, chain=CHAIN):
        op.execute(statement)


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect in ("postgresql", "mssql"):
        for statement in isolation_drop_ddl(_marked(), dialect):
            op.execute(statement)
    if dialect == "postgresql":
        op.add_column("kb_chunks", sa.Column("tsv", postgresql.TSVECTOR(), sa.Computed(CHUNK_TSV, persisted=True)))
        op.execute("CREATE INDEX ix_kb_chunks_tsv ON kb_chunks USING gin (tsv)")
    with op.batch_alter_table("kb_chunks") as b:
        b.drop_column("metadata")
    op.drop_table(TABLE)
