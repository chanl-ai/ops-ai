"""kb-service's tables are held to the caller's tenant and team by the database (c-507)

Revision ID: kb_0011
Revises: kb_0010

Every store query filtered by the tenant it was given, and nothing in the database stopped one that did not. Each
table now carries its own team and the generated team policy (ops_store.schema.isolation_ddl) for the role every
transaction runs as, ops_kb_tenant. The start-up move between file stores reads which tenants hold a source as
ops_kb_system (BYPASSRLS), granted that read alone.

A link takes its base's team; a document, a run and a change take their source's; a version and a chunk take their
document's. A row whose parent is gone (a retired base, a change kept after its document was removed) takes NO_TEAM,
which matches no team: only a tenant-wide transaction reads it.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mssql

from ops_store.schema import (
    TEAM_OWNED,
    TENANT_SCOPED,
    isolation_ddl,
    isolation_drop_ddl,
    member_ddl,
    mssql_predicates_ddl,
    role_ddl,
)

revision = "kb_0011"
down_revision = "kb_0010"
branch_labels = None
depends_on = None

CHAIN = "kb"
ROLE = "ops_kb_tenant"
SYSTEM_ROLE = "ops_kb_system"
LOGIN = "ops_kb_runtime"
NO_TEAM = ""
# Each table that gains a team, with the parent (table, the child's key column) it takes the team from, in order: a
# version and a chunk read their document's team, so documents come first.
CHILDREN: dict[str, tuple[str, str] | None] = {
    "kb_base_sources": ("kb_bases", "kb_id"),
    "kb_items": ("kb_sources", "source_id"),
    "kb_item_versions": ("kb_items", "item_id"),
    "kb_chunks": ("kb_items", "item_id"),
    "kb_changes": ("kb_sources", "source_id"),
    "kb_runs": ("kb_sources", "source_id"),
    "kb_retired_bases": None,
}
TABLES = ("kb_bases", "kb_sources", *CHILDREN)


def _marked(name: str) -> sa.Table:
    return sa.Table(
        name,
        sa.MetaData(),
        sa.Column("tenant_id", sa.String(64)),
        sa.Column("team_id", sa.String(64)),
        info={**TENANT_SCOPED, **TEAM_OWNED},
    )


def _column_type(column: sa.Column[Any]) -> str:
    return column.type.compile(dialect=mssql.dialect())


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        # The migrating role may own the tables; once FORCE is on, row-level security would hide rows from it.
        op.execute("SET LOCAL row_security = off")
    for name, parent in CHILDREN.items():
        with op.batch_alter_table(name) as b:
            b.add_column(sa.Column("team_id", sa.String(64)))
        t = sa.table(name, sa.column("tenant_id", sa.String), sa.column("team_id", sa.String))
        if parent is None:
            op.execute(sa.update(t).values(team_id=NO_TEAM))
        else:
            parent_table, key = parent
            child = sa.table(
                name, sa.column("tenant_id", sa.String), sa.column(key, sa.String), sa.column("team_id", sa.String)
            )
            p = sa.table(
                parent_table,
                sa.column("tenant_id", sa.String),
                sa.column("id", sa.String),
                sa.column("team_id", sa.String),
            )
            team = (
                sa.select(p.c.team_id)
                .where(p.c.tenant_id == child.c.tenant_id, p.c.id == child.c[key])
                .scalar_subquery()
            )
            op.execute(sa.update(child).values(team_id=sa.func.coalesce(team, NO_TEAM)))
        with op.batch_alter_table(name) as b:
            b.alter_column("team_id", existing_type=sa.String(64), nullable=False)
    # A base's name is unique in its team; another team's names are not seen by a team's transaction.
    with op.batch_alter_table("kb_bases") as b:
        b.drop_constraint("uq_kb_bases_name", type_="unique")
        b.create_unique_constraint("uq_kb_bases_name", ["tenant_id", "team_id", "name"])
    tables = [_marked(n) for n in TABLES]
    if dialect == "postgresql":
        op.execute(role_ddl(ROLE))
        op.execute(role_ddl(SYSTEM_ROLE, bypass=True))
        for t in tables:
            op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {t.name} TO {ROLE}")
        op.execute(f"GRANT SELECT ON kb_sources TO {SYSTEM_ROLE}")
        for role in (ROLE, SYSTEM_ROLE):
            op.execute(member_ddl(role, LOGIN))
    elif dialect == "mssql":
        for statement in mssql_predicates_ddl(CHAIN, tables, column_type=_column_type, system_user=None):
            op.execute(statement)
    else:
        return
    for t in tables:
        for statement in isolation_ddl(t, dialect, chain=CHAIN):
            op.execute(statement)


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect in ("postgresql", "mssql"):
        for name in TABLES:
            for statement in isolation_drop_ddl(_marked(name), dialect):
                op.execute(statement)
    if dialect == "postgresql":
        for name in TABLES:
            op.execute(f"REVOKE ALL ON {name} FROM {ROLE}")
        op.execute(f"REVOKE ALL ON kb_sources FROM {SYSTEM_ROLE}")
    # Back to one name per tenant: a name two teams hold keeps it in the first team (by team id); the others' bases
    # take their team's id after it, so the tenant-wide constraint can be made.
    op.execute(
        sa.text(
            "UPDATE kb_bases SET name = name || ' (' || team_id || ')' WHERE EXISTS (SELECT 1 FROM kb_bases o "
            "WHERE o.tenant_id = kb_bases.tenant_id AND lower(o.name) = lower(kb_bases.name) "
            "AND o.team_id < kb_bases.team_id)"
        )
    )
    with op.batch_alter_table("kb_bases") as b:
        b.drop_constraint("uq_kb_bases_name", type_="unique")
        b.create_unique_constraint("uq_kb_bases_name", ["tenant_id", "name"])
    for name in reversed(list(CHILDREN)):
        with op.batch_alter_table(name) as b:
            b.drop_column("team_id")
