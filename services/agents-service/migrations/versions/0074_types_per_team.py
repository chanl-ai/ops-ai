"""Every task and case type belongs to one team, and no team policy reads a row with no team (c-507)

Revision ID: 0074_types_per_team
Revises: 0073_run_tables_team

A seeded type had no team and every team read it, so a team's tasks and cases depended on a record another team's
admin could change. Each type is now keyed (tenant, team, id): a type with no team is copied, with every version, into
each team that has work in the tenant (a conversation, a workflow, a run or a case), then removed; a team with no
work yet gets the seeds on its first read (task_type_seeds.py, case_type_seeds.py). Ids stay the same, so a workflow's
`taskType` and a case's pinned `type_id` resolve to the copy in their own team with no rewrite.

The team policy loses its no-team branch (ops_store.schema): the run tables of 0073 and both type tables get it
reissued, and the version tables, which were read through their type, carry their own team and policy. On SQL Server
the chain's team predicate functions are bound to every team policy, so all of them are dropped and created again.
Runs on PostgreSQL and SQL Server.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy.dialects import mssql

from ops_store.schema import (
    TEAM_OWNED,
    TENANT_SCOPED,
    isolation_ddl,
    isolation_drop_ddl,
    mssql_team_predicates_reissue_ddl,
)

revision = "0074_types_per_team"
down_revision = "0073_run_tables_team"
branch_labels = None
depends_on = None

CHAIN = "agents"
SYSTEM_USER = "ops_runtime_system"
KINDS = ("task", "case")
RUN_TABLES = ("graph_threads", "graph_runs", "thread_events", "review_decisions", "review_approvals")
# Tables whose rows say which teams have work in a tenant: conversations, workflow runs and their definitions, cases.
WORK = ("graph_threads", "engine_runs", "engine_definitions", "cases")
HEAD = ("tenant_id", "id", "origin", "name", "description", "version", "published_version", "copied_from")
STAMPS = ("created_at", "created_by", "updated_at", "updated_by")
VERSION = ("tenant_id", "type_id", "version", "record", "saved_at", "saved_by", "published_at", "published_by")


def _marked(name: str) -> sa.Table:
    """The table as far as its isolation needs, as of this revision."""
    return sa.Table(
        name,
        sa.MetaData(),
        sa.Column("tenant_id", sa.String(64)),
        sa.Column("team_id", sa.String(64)),
        info={**TENANT_SCOPED, **TEAM_OWNED},
    )


def _column_type(column: sa.Column[Any]) -> str:
    return column.type.compile(dialect=mssql.dialect())


def _team_tables() -> list[str]:
    return [*RUN_TABLES, *(f"{k}_types" for k in KINDS), *(f"{k}_type_versions" for k in KINDS)]


def _isolate(*, reads_no_team: bool, version_kind: str) -> None:
    """Every team table of the chain under the team policy (with or without the no-team branch); the version tables
    under `version_kind` (team after this revision, tenant before it)."""
    dialect = op.get_bind().dialect.name
    if dialect not in ("postgresql", "mssql"):
        return
    versions = [f"{k}_type_versions" for k in KINDS]
    teams = [_marked(t) for t in _team_tables() if version_kind == "team" or t not in versions]
    if dialect == "mssql":
        if version_kind == "tenant":
            # Back under the tenant policy before the team functions are dropped and made again without them.
            for t in versions:
                for statement in isolation_ddl(_marked(t), dialect, kind="tenant", chain=CHAIN):
                    op.execute(statement)
        for statement in mssql_team_predicates_reissue_ddl(
            CHAIN, teams, column_type=_column_type, system_user=SYSTEM_USER, reads_no_team=reads_no_team
        ):
            op.execute(statement)
        return
    for t in teams:
        for statement in isolation_ddl(t, dialect, kind="team", reads_no_team=reads_no_team):
            op.execute(statement)
    if version_kind == "tenant":
        for t in versions:
            for statement in isolation_ddl(_marked(t), dialect, kind="tenant"):
                op.execute(statement)


def _teams() -> sa.Subquery:
    """(tenant_id, team_id) of every team with work in a tenant."""
    selects: list[sa.Select[Any, Any]] = []
    for name in (*WORK, *(f"{k}_types" for k in KINDS)):
        t = sa.table(name, sa.column("tenant_id", sa.String), sa.column("team_id", sa.String))
        selects.append(sa.select(t.c.tenant_id, t.c.team_id).where(t.c.team_id.is_not(None)).distinct())
    return sa.union(*selects).subquery("teams")


def _copy_to_teams(kind: str) -> None:
    head = sa.table(f"{kind}_types", *(sa.column(c, sa.String) for c in (*HEAD, *STAMPS, "team_id")))
    versions = sa.table(f"{kind}_type_versions", *(sa.column(c, sa.String) for c in (*VERSION, "team_id")))
    teams = _teams()
    mine = head.alias("mine")
    # Versions first: they are found through the no-team type, which the head copies leave in place until the delete.
    source = head.alias("source")
    copy_versions = (
        sa.select(*(versions.c[c] for c in VERSION), teams.c.team_id)
        .select_from(
            versions.join(
                source, sa.and_(source.c.tenant_id == versions.c.tenant_id, source.c.id == versions.c.type_id)
            ).join(teams, teams.c.tenant_id == versions.c.tenant_id)
        )
        .where(
            source.c.team_id.is_(None),
            versions.c.team_id.is_(None),
            ~sa.exists().where(
                mine.c.tenant_id == versions.c.tenant_id, mine.c.team_id == teams.c.team_id, mine.c.id == source.c.id
            ),
        )
    )
    op.execute(versions.insert().from_select([*VERSION, "team_id"], copy_versions))
    copy_heads = (
        sa.select(*(head.c[c] for c in (*HEAD, *STAMPS)), teams.c.team_id)
        .select_from(head.join(teams, teams.c.tenant_id == head.c.tenant_id))
        .where(
            head.c.team_id.is_(None),
            ~sa.exists().where(
                mine.c.tenant_id == head.c.tenant_id, mine.c.team_id == teams.c.team_id, mine.c.id == head.c.id
            ),
        )
    )
    op.execute(head.insert().from_select([*HEAD, *STAMPS, "team_id"], copy_heads))


def _release_types() -> None:
    """The type tables leave their policies while their team columns change: a policy binds the columns it reads
    (SQL Server's schema binding, PostgreSQL's dependency on a dropped column). `_isolate` puts them back."""
    dialect = op.get_bind().dialect.name
    if dialect not in ("postgresql", "mssql"):
        return
    for k in KINDS:
        for t in (f"{k}_types", f"{k}_type_versions"):
            for statement in isolation_drop_ddl(_marked(t), dialect):
                op.execute(statement)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # The migrating role may own the tables; FORCE row-level security would otherwise hide every row from it.
        op.execute("SET LOCAL row_security = off")
    _release_types()
    for k in KINDS:
        # The old keys go first: a team's copy repeats the (tenant, id) and (tenant, type_id, version) they held unique.
        for table in (f"{k}_types", f"{k}_type_versions"):
            op.drop_constraint(f"{table}_pkey", table, type_="primary")
        with op.batch_alter_table(f"{k}_type_versions") as b:
            b.add_column(sa.Column("team_id", sa.String(64)))
        head = sa.table(f"{k}_types", sa.column("tenant_id"), sa.column("id"), sa.column("team_id"))
        versions = sa.table(f"{k}_type_versions", sa.column("tenant_id"), sa.column("type_id"), sa.column("team_id"))
        owner = (
            sa.select(head.c.team_id)
            .where(head.c.tenant_id == versions.c.tenant_id, head.c.id == versions.c.type_id)
            .scalar_subquery()
        )
        op.execute(sa.update(versions).values(team_id=owner))
        _copy_to_teams(k)
        if not context.is_offline_mode():
            gone = bind.execute(
                sa.select(head.c.tenant_id, head.c.id).where(head.c.team_id.is_(None)).order_by("tenant_id", "id")
            ).all()
            for tenant, type_id in gone:
                print(f"0074_types_per_team: removed no-team {k} type {type_id} of {tenant}, copied into its teams")
        op.execute(sa.delete(versions).where(versions.c.team_id.is_(None)))
        op.execute(sa.delete(head).where(head.c.team_id.is_(None)))
        for table, key in ((f"{k}_types", "id"), (f"{k}_type_versions", "type_id")):
            columns = ["tenant_id", "team_id", key] + (["version"] if table.endswith("versions") else [])
            with op.batch_alter_table(table) as b:
                b.alter_column("team_id", existing_type=sa.String(64), nullable=False)
            op.create_primary_key(f"{table}_pkey", table, columns)
    _isolate(reads_no_team=False, version_kind="team")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("SET LOCAL row_security = off")
    _release_types()
    for k in reversed(KINDS):
        # Back to one type per (tenant, id): the copy of the first team in id order stays, the others go; nothing is
        # merged back.
        for table, key in ((f"{k}_type_versions", "type_id"), (f"{k}_types", "id")):
            op.execute(
                sa.text(
                    f"DELETE FROM {table} WHERE EXISTS (SELECT 1 FROM {table} o WHERE o.tenant_id = {table}.tenant_id "
                    f"AND o.{key} = {table}.{key} AND o.team_id < {table}.team_id)"
                )
            )
        for table, key in ((f"{k}_types", "id"), (f"{k}_type_versions", "type_id")):
            columns = ["tenant_id", key] + (["version"] if table.endswith("versions") else [])
            op.drop_constraint(f"{table}_pkey", table, type_="primary")
            op.create_primary_key(f"{table}_pkey", table, columns)
        with op.batch_alter_table(f"{k}_types") as b:
            b.alter_column("team_id", existing_type=sa.String(64), nullable=True)
        with op.batch_alter_table(f"{k}_type_versions") as b:
            b.drop_column("team_id")
    _isolate(reads_no_team=True, version_kind="tenant")
