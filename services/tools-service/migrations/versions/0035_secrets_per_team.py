"""A secret belongs to one team (c-509)

Revision ID: tools_0035_secrets_per_team
Revises: tools_0034_tools_per_team

A secret was one row per name in the tenant, limited to some teams by its `teams` list or read by every team. Each team
now holds its own rows: a team's modules and connections read only their team's secret, so two teams that call the same
system each keep a row under the same name. The key becomes (tenant, team, name).

Each row goes to the teams it was limited to, or, when it named none, to every team whose modules name `{{NAME}}` in an
operation or a published baseline; a connection's secret part goes to the connection's team. A row owned by several
teams is copied into each, ciphertext and version unchanged (its key context is the tenant and name). A row no team
reads is deleted (owner, 2026-10-26: existing data is test data); where model provider keys live is the owner's
decision still to come. An audit row keeps the history of a name one team owns; the rest are deleted with it.

The steps are SQL, so the revision renders offline for both databases.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "tools_0035_secrets_per_team"
down_revision = "tools_0034_tools_per_team"
branch_labels = None
depends_on = None

COLUMNS = (
    "tenant_id, name, ciphertext, version, created_by, created_at, rotated_at, last_used_at, template_id, protection, "
    "connection_id"
)


def _owners(dialect: str) -> str:
    """(tenant_id, name, team_id) for every team that owns a secret, by the rules in the docstring."""
    if dialect == "mssql":
        listed = (
            "SELECT s.tenant_id, s.name, j.value AS team_id FROM tool_secrets s CROSS APPLY OPENJSON("
            "CASE WHEN ISJSON(s.teams) = 1 AND LEFT(LTRIM(s.teams), 1) = '[' THEN s.teams ELSE '[]' END) j "
            "WHERE s.connection_id IS NULL"
        )
        unlisted = "COALESCE(s.teams, 'null') IN ('null', '[]')"
        ref = "'{{' + s.name + '}}'"

        def names(text: str) -> str:
            return f"CHARINDEX({ref}, {text}) > 0"

    else:
        listed = (
            "SELECT s.tenant_id, s.name, j.value AS team_id FROM tool_secrets s CROSS JOIN LATERAL "
            "json_array_elements_text("
            "CASE WHEN json_typeof(s.teams) = 'array' THEN s.teams ELSE CAST('[]' AS json) END) "
            "AS j(value) WHERE s.connection_id IS NULL"
        )
        unlisted = "COALESCE(CAST(s.teams AS TEXT), 'null') IN ('null', '[]')"
        ref = "'{{' || s.name || '}}'"

        def names(text: str) -> str:
            return f"strpos(CAST({text} AS TEXT), {ref}) > 0"

    return (
        "SELECT s.tenant_id, s.name, c.team_id FROM tool_secrets s JOIN connections c "
        "ON c.tenant_id = s.tenant_id AND c.id = s.connection_id "
        f"UNION {listed} "
        "UNION SELECT s.tenant_id, s.name, m.team_id FROM tool_secrets s JOIN tool_modules m "
        "ON m.tenant_id = s.tenant_id AND m.team_id IS NOT NULL "
        f"WHERE s.connection_id IS NULL AND {unlisted} AND ({names('m.baseline')} OR EXISTS ("
        "SELECT 1 FROM module_operations o WHERE o.tenant_id = m.tenant_id AND o.module_id = m.id "
        f"AND ({names('o.path')} OR {names('o.headers')})))"
    )


def upgrade() -> None:
    dialect = op.get_context().dialect.name
    op.drop_constraint("tool_secrets_pkey", "tool_secrets", type_="primary")
    op.add_column("tool_secrets", sa.Column("team_id", sa.String(64)))
    op.add_column("secret_audit", sa.Column("team_id", sa.String(64)))
    # One row per owning team; then every team-less row goes, the originals and those no team reads.
    op.execute(
        f"INSERT INTO tool_secrets ({COLUMNS}, team_id) "
        f"SELECT {', '.join('s.' + c.strip() for c in COLUMNS.split(','))}, o.team_id "
        f"FROM tool_secrets s JOIN ({_owners(dialect)}) o ON o.tenant_id = s.tenant_id AND o.name = s.name "
        "WHERE s.team_id IS NULL AND o.team_id IS NOT NULL"
    )
    op.execute("DELETE FROM tool_secrets WHERE team_id IS NULL")
    op.execute(
        "UPDATE secret_audit SET team_id = (SELECT MIN(s.team_id) FROM tool_secrets s "
        "WHERE s.tenant_id = secret_audit.tenant_id AND s.name = secret_audit.name) "
        "WHERE (SELECT COUNT(*) FROM tool_secrets s WHERE s.tenant_id = secret_audit.tenant_id "
        "AND s.name = secret_audit.name) = 1"
    )
    op.execute("DELETE FROM secret_audit WHERE team_id IS NULL")
    op.drop_column("tool_secrets", "teams")
    op.alter_column("tool_secrets", "team_id", existing_type=sa.String(64), nullable=False)
    op.alter_column("secret_audit", "team_id", existing_type=sa.String(64), nullable=False)
    op.create_primary_key("tool_secrets_pkey", "tool_secrets", ["tenant_id", "team_id", "name"])


def downgrade() -> None:
    """Back to one row per name: the first team's copy stays, limited to every team that held one."""
    dialect = op.get_context().dialect.name
    op.drop_constraint("tool_secrets_pkey", "tool_secrets", type_="primary")
    op.add_column("tool_secrets", sa.Column("teams", sa.JSON))
    if dialect == "mssql":
        teams = (
            "(SELECT '[' + STRING_AGG('\"' + t.team_id + '\"', ',') WITHIN GROUP (ORDER BY t.team_id) + ']' "
            "FROM tool_secrets t WHERE t.tenant_id = tool_secrets.tenant_id AND t.name = tool_secrets.name "
            "AND t.team_id IS NOT NULL)"
        )
    else:
        teams = (
            "(SELECT json_agg(t.team_id ORDER BY t.team_id) FROM tool_secrets t "
            "WHERE t.tenant_id = tool_secrets.tenant_id AND t.name = tool_secrets.name AND t.team_id IS NOT NULL)"
        )
    op.execute(f"UPDATE tool_secrets SET teams = {teams} WHERE team_id IS NOT NULL")
    op.execute(
        "DELETE FROM tool_secrets WHERE team_id IS NOT NULL AND EXISTS (SELECT 1 FROM tool_secrets t "
        "WHERE t.tenant_id = tool_secrets.tenant_id AND t.name = tool_secrets.name "
        "AND t.team_id < tool_secrets.team_id)"
    )
    op.drop_column("secret_audit", "team_id")
    op.drop_column("tool_secrets", "team_id")
    op.create_primary_key("tool_secrets_pkey", "tool_secrets", ["tenant_id", "name"])
