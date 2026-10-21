"""`team_visible` (c-407), by failure mode: a nullable team column whose workspace-level rows (null team) are hidden
from a team, and a NOT NULL team column whose filter carries `OR team IS NULL`, which stops the planner seeking on the
(tenant_id, team_id, ...) index of a team's list (c-429, tests/engine/test_hot_query_indexes.py in agents-service)."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from ops_store.schema import TEAM_OWNED
from ops_store.team_scope import acting_as, team_visible

meta = sa.MetaData()
shared = sa.Table("tv_shared", meta, sa.Column("id", sa.String(8)), sa.Column("team_id", sa.String(8)), info=TEAM_OWNED)
strict = sa.Table(
    "tv_strict",
    meta,
    sa.Column("id", sa.String(8)),
    sa.Column("team_id", sa.String(8), nullable=False),
    info=TEAM_OWNED,
)


def sql(clause: sa.ColumnElement[bool]) -> str:
    return str(clause.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


def test_a_nullable_team_column_shows_the_team_and_the_workspace_level_rows() -> None:
    with acting_as("team_a"):
        assert sql(team_visible(shared)) == "tv_shared.team_id = 'team_a' OR tv_shared.team_id IS NULL"


def test_a_not_null_team_column_is_a_bare_equality_the_index_can_seek_on() -> None:
    with acting_as("team_a"):
        assert sql(team_visible(strict)) == "tv_strict.team_id = 'team_a'"
