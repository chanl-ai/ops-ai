"""Each agent's skill pins in a table of their own

Revision ID: 0113_agent_skill_pins
Revises: 0112_definitions_list_indexes

The skills list counts, for each skill, the agents whose newest version pins it and how many of those are live. The
pins lived only inside each version's spec, so the list read every agent's newest version and counted in Python, one
read per agent. `agent_skill_pins` holds one row per agent and pinned skill (the skill version, the agent's tenant and
team), written in the transaction that saves the version (store/agent_registry.py), with the team policy every
team-owned table carries. The list also filters one team's skills by owner team and by origin, which two indexes on
registry_skills serve.

The rows are filled from each agent's newest version's `spec.skillPins` (the first pin of a skill named twice; an
entry that is not an object with a skillId of at most 64 characters and a whole version is skipped and counted): listed
once in a session table, inside the migration's transaction, with the source tables' own policies set aside (on SQL
Server each is dropped and made again before that transaction ends), then written BATCH rows at a time, each batch
committed alone, so no lock lasts the whole fill. A row already there is skipped, so a fill that stops part way can
run again. Stop agents-service before upgrading (docs/deploy/database.md).

The down path drops the table and its policy. No pin is lost: each row copies an entry of the newest version's
`spec.skillPins`, which the store writes in the same transaction (store/agent_registry.py `hold_pins`) and the down
path leaves in place, and upgrading again fills the table from there. Runs on PostgreSQL and SQL Server.
"""

from __future__ import annotations

import logging
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mssql

from ops_store.schema import (
    TEAM_OWNED,
    TENANT_SCOPED,
    backfill_ddl,
    isolation_ddl,
    isolation_drop_ddl,
    mssql_predicates_ddl,
    mssql_quiet_batch,
    session_table_ddl,
)

revision = "0113_agent_skill_pins"
down_revision = "0112_definitions_list_indexes"
branch_labels = None
depends_on = None

CHAIN = "agents"
TENANT_ROLE = "ops_runtime_tenant"
SYSTEM_ROLE = "ops_runtime_system"
TABLE = "agent_skill_pins"
INDEX = "ix_agent_skill_pins_team_skill"
# The skills list filters one team's skills by owner team and by origin.
SKILL_INDEXES = {
    "ix_registry_skills_team_owner": ["tenant_id", "team_id", "owner_team"],
    "ix_registry_skills_team_origin": ["tenant_id", "team_id", "origin"],
}
# Rows per committed batch; under 5000, where SQL Server escalates row locks to a table lock.
BATCH = 4000
COLUMNS = ("tenant_id", "team_id", "agent_id", "skill_id", "version")
log = logging.getLogger("alembic.runtime.migration")


def _marked(name: str, *, team: bool) -> sa.Table:
    """The table as far as its policy needs, as of this revision."""
    columns = [sa.Column("tenant_id", sa.String(64)), *([sa.Column("team_id", sa.String(64))] if team else [])]
    return sa.Table(name, sa.MetaData(), *columns, info={**TENANT_SCOPED, **TEAM_OWNED} if team else TENANT_SCOPED)


def _column_type(column: sa.Column[Any]) -> str:
    return column.type.compile(dialect=mssql.dialect())


def _entries(dialect: str) -> tuple[str, str, str, str, str]:
    """(FROM clause of every `skillPins` entry of each agent's newest version, its position, skill id, version, the
    condition a usable entry meets), as SQL. A usable entry is an object whose skillId is 1 to 64 characters and whose
    version is a whole number of at most nine digits; anything else (1.5, "abc", a longer id, a bare string) is
    skipped, so one malformed spec cannot stop the upgrade. Read as text and checked before any cast, since each
    database refuses a bad cast differently."""
    newest = (
        "FROM registry_agents a JOIN registry_agent_versions v "
        "ON v.agent_id = a.id AND v.version = a.version AND v.tenant_id = a.tenant_id "
    )
    if dialect == "mssql":
        # The default schema gives each entry's position ([key]) and JSON type (5: an object); JSON_VALUE reads an
        # entry only once CASE has seen it is an object, since it raises on anything that is not JSON text.
        source = newest + (
            "CROSS APPLY OPENJSON(CASE WHEN LEFT(JSON_QUERY(v.spec, '$.skillPins'), 1) = '[' "
            "THEN JSON_QUERY(v.spec, '$.skillPins') END) e "
        )
        skill = "CASE WHEN e.type = 5 THEN JSON_VALUE(e.value, '$.skillId') END"
        version = "CASE WHEN e.type = 5 THEN JSON_VALUE(e.value, '$.version') END"
        usable = (
            f"e.type = 5 AND LEN({skill}) BETWEEN 1 AND 64 AND LEN({version}) BETWEEN 1 AND 9 "
            f"AND {version} NOT LIKE '%[^0-9-]%' AND TRY_CAST({version} AS INT) IS NOT NULL"
        )
        return source, "CAST(e.[key] AS INT)", skill, version, usable
    held = "json_extract_path(v.spec, 'skillPins')"
    source = newest + (
        f"CROSS JOIN LATERAL json_array_elements(CASE WHEN json_typeof({held}) = 'array' THEN {held} "
        "ELSE CAST('[]' AS JSON) END) WITH ORDINALITY AS e(value, n) "
    )
    skill, version = "(e.value ->> 'skillId')", "(e.value ->> 'version')"
    usable = (
        f"json_typeof(e.value) = 'object' AND char_length({skill}) BETWEEN 1 AND 64 AND {version} ~ '^-?[0-9]{{1,9}}$'"
    )
    return source, "e.n", skill, version, usable


def _list_pins(dialect: str) -> str:
    """A session table of every agent's newest pins, one row per agent and skill, the first pin of a skill named twice
    (as store/agent_registry.py pins_of keeps); returns its name. Logs how many entries were skipped as unusable."""
    copy = "#pins_0113" if dialect == "mssql" else "pins_0113"
    op.execute(
        session_table_ddl(
            copy,
            dialect,
            [("k", 130), ("tenant_id", 64), ("team_id", 64), ("agent_id", 64), ("skill_id", 64), ("version", 12)],
        )
    )
    source, position, skill, version, usable = _entries(dialect)
    if not op.get_context().as_sql:
        skipped = op.get_bind().execute(sa.text(f"SELECT COUNT(*) {source}WHERE NOT ({usable})")).scalar_one()
        if skipped:
            log.warning(
                "0113: skipped %d skill pin entries that are not an object with a skillId and a whole version", skipped
            )
    key = f"a.id + '/' + {skill}" if dialect == "mssql" else f"a.id || '/' || {skill}"
    op.execute(
        f"INSERT INTO {copy} (k, tenant_id, team_id, agent_id, skill_id, version) "
        "SELECT p.k, p.tenant_id, p.team_id, p.agent_id, p.skill_id, p.version FROM ("
        f"SELECT {key} AS k, a.tenant_id, a.team_id, a.id AS agent_id, {skill} AS skill_id, {version} AS version, "
        f"ROW_NUMBER() OVER (PARTITION BY a.id, {skill} ORDER BY {position}) AS r "
        f"{source}WHERE {usable}) p WHERE p.r = 1"
    )
    return copy


def _fill(dialect: str, copy: str) -> str:
    """Writes the listed pins BATCH rows at a time, each batch committed on its own; a row already there is skipped."""
    names = ", ".join(COLUMNS)
    picked = "s.tenant_id, s.team_id, s.agent_id, s.skill_id, CAST(s.version AS INTEGER)"
    absent = f"NOT EXISTS (SELECT 1 FROM {TABLE} t WHERE t.agent_id = s.agent_id AND t.skill_id = s.skill_id)"
    if dialect == "mssql":
        return mssql_quiet_batch(
            f"WHILE 1 = 1\nBEGIN\n"
            f"    INSERT INTO {TABLE} ({names}) SELECT TOP ({BATCH}) {picked} FROM {copy} s WHERE {absent};\n"
            f"    IF @@ROWCOUNT = 0 BREAK;\nEND"
        )
    return (
        f"DO $$\nDECLARE n integer;\nBEGIN\n    LOOP\n"
        f"        INSERT INTO {TABLE} ({names}) SELECT {picked} FROM {copy} s WHERE {absent} LIMIT {BATCH};\n"
        f"        GET DIAGNOSTICS n = ROW_COUNT;\n        EXIT WHEN n = 0;\n        COMMIT;\n    END LOOP;\nEND $$"
    )


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    op.create_table(
        TABLE,
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column(
            "agent_id",
            sa.String(64),
            # Named as PostgreSQL names it, so both databases (and the golden DDL) hold the same key.
            sa.ForeignKey("registry_agents.id", ondelete="CASCADE", name="agent_skill_pins_agent_id_fkey"),
            primary_key=True,
        ),
        sa.Column("skill_id", sa.String(64), primary_key=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("team_id", sa.String(64), nullable=False),
    )
    op.create_index(INDEX, TABLE, ["tenant_id", "team_id", "skill_id"])
    for name, columns in SKILL_INDEXES.items():
        op.create_index(name, "registry_skills", columns)
    if dialect not in ("postgresql", "mssql"):
        return
    sources = [_marked("registry_agents", team=True)]
    before, after = backfill_ddl(sources, dialect, chain=CHAIN, kind="team")
    tenant_before, tenant_after = backfill_ddl(
        [_marked("registry_agent_versions", team=False)], dialect, chain=CHAIN, kind="tenant"
    )
    for statement in (*before, *tenant_before):
        op.execute(statement)
    copy = _list_pins(dialect)
    for statement in (*after, *tenant_after):
        op.execute(statement)
    with op.get_context().autocommit_block():
        op.execute(_fill(dialect, copy))
    op.execute(f"DROP TABLE {copy}")
    table = _marked(TABLE, team=True)
    if dialect == "mssql":
        for statement in mssql_predicates_ddl(CHAIN, [table], column_type=_column_type, system_user=SYSTEM_ROLE):
            op.execute(statement)
    else:
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {TABLE} TO {TENANT_ROLE}")
    for statement in isolation_ddl(table, dialect, kind="team", chain=CHAIN):
        op.execute(statement)


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect in ("postgresql", "mssql"):
        for statement in isolation_drop_ddl(_marked(TABLE, team=True), dialect):
            op.execute(statement)
    for name in SKILL_INDEXES:
        op.drop_index(name, table_name="registry_skills")
    op.drop_index(INDEX, table_name=TABLE)
    op.drop_table(TABLE)
