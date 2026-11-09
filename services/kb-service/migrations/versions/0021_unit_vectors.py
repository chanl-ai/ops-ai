"""Index units keep a vector, for search by meaning

kb_unit_vectors holds each index unit's embedding with the model and width it was made with, so a change of the
environment's embedding model embeds every unit again and reads nothing again. On PostgreSQL the vectors live in
pgvector, which this revision requires: `CREATE EXTENSION vector` needs a superuser, so a database installed by a DBA
has it created by the DBA first (docs/deploy/database.md), and IF NOT EXISTS then changes nothing. An HNSW index serves
the environment's width (OPS_EMBEDDING_WIDTH). SQL Server and SQLite get no vector table yet (decision D17), and
kb-service searches there on keywords only, saying so in each result.

A base made while keyword search was the default stored that default whole; one still holding it unchanged, for any of
the three presets, searches both lanes from now on, as a new base does. A base whose settings were changed since keeps
its searchMode, since "keyword" there may have been chosen, and the downgrade sets back only the bases the upgrade
moved. Every statement renders offline, so an upgrade bundle can carry it.

Revision ID: kb_0021
Revises: kb_0020
"""

from __future__ import annotations

import json
from typing import Any

import sqlalchemy as sa
from alembic import op

from ops_service_kit.settings import Settings
from ops_store.dialect import Vector, vector_index_ddl
from ops_store.schema import TEAM_OWNED, TENANT_SCOPED, backfill_ddl, isolation_ddl, isolation_drop_ddl

revision = "kb_0021"
down_revision = "kb_0020"
branch_labels = None
depends_on = None

CHAIN = "kb"
ROLE = "ops_kb_tenant"
TABLE = "kb_unit_vectors"
# A new base's retrieval settings before meaning search (service.DEFAULT_RETRIEVAL and PRESETS then), frozen here: the
# rows to move are the ones still holding one of them as written, text for text.
_OLD_DEFAULT: dict[str, Any] = {
    "searchMode": "keyword",
    "hybridWeight": 0.6,
    "rerank": False,
    "reranker": "hosted",
    "chunkLimit": 8,
    "threshold": 0.5,
    "asOf": "",
    "rewrite": "off",
    "expandCount": 3,
    "rewriteInstructions": "",
    "scopeSourceIds": [],
    "answerShape": "answer_with_citations",
    "model": "bank-standard",
    "temperature": 0.1,
    "maxTokens": 800,
    "instructions": "Answer only from the provided context. If the context does not contain the answer, say so.",
    "citationStyle": "inline",
    "includeChunks": True,
    "noAnswerMessage": "I could not find that in the knowledge base.",
    "filters": {"match": "all", "conditions": []},
    "tagsInclude": [],
    "tagsExclude": [],
    "includeUntagged": True,
    "structuredTables": False,
}
_OLD_PRESETS: tuple[dict[str, Any], ...] = (
    {"chunkLimit": 8, "threshold": 0.5, "answerShape": "answer_with_citations"},
    {"chunkLimit": 5, "threshold": 0.65, "answerShape": "answer_with_citations"},
    {"chunkLimit": 10, "threshold": 0.4, "answerShape": "chunks"},
)
# json.dumps as the JSON column writes it, and compact, as a JSON column on another driver may.
_SEPARATORS = ((", ", ": "), (",", ":"))


def _moves() -> list[tuple[str, str]]:
    """(stored default, the same with both lanes) for each preset and spelling."""
    out: list[tuple[str, str]] = []
    for preset in _OLD_PRESETS:
        old = {**_OLD_DEFAULT, **preset}
        for sep in _SEPARATORS:
            out.append((json.dumps(old, separators=sep), json.dumps({**old, "searchMode": "hybrid"}, separators=sep)))
    return out


def _swap(dialect: str, frm: str, to: str) -> sa.Update:
    """Built, not written as text: the JSON holds colons, which text SQL reads as bind parameters."""
    bases = sa.table("kb_bases", sa.column("retrieval", sa.Text))
    value: sa.ColumnElement[Any] = sa.literal(to, sa.Text)
    if dialect == "postgresql":
        value = sa.cast(value, sa.JSON)
    return sa.update(bases).where(sa.cast(bases.c.retrieval, sa.Text) == frm).values(retrieval=value)


def _move_defaults(dialect: str, *, back: bool) -> None:
    if dialect not in ("postgresql", "mssql", "sqlite"):
        return
    # The migrate login moves every tenant's bases, past each base's isolation.
    before, after = backfill_ddl([_marked("kb_bases")], dialect, chain=CHAIN)
    swaps = [_swap(dialect, new, old) if back else _swap(dialect, old, new) for old, new in _moves()]
    for statement in [*before, *swaps, *after]:
        op.execute(statement)


def _marked(name: str = TABLE) -> sa.Table:
    return sa.Table(
        name,
        sa.MetaData(),
        sa.Column("tenant_id", sa.String(64)),
        sa.Column("team_id", sa.String(64)),
        info={**TENANT_SCOPED, **TEAM_OWNED},
    )


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    _move_defaults(dialect, back=False)
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
    dialect = op.get_bind().dialect.name
    _move_defaults(dialect, back=True)
    if dialect != "postgresql":
        return
    for statement in isolation_drop_ddl(_marked(), "postgresql"):
        op.execute(statement)
    op.drop_table(TABLE)
