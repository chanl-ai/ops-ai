"""A skill's owner team is the id of the team that holds it

Revision ID: 20261124_0257_skill_owner_ids
Revises: 0120_model_call_reservations

`registry_skills.owner_team` was free text: the console, templates and the team assistant wrote a team id, while the
sample team, the examples and earlier option lists wrote a team name, so the Skills list showed ids beside names. The
column now holds a team id, checked against the teams the caller may create skills in, and the name is read from
platform-service when a skill is read. This service holds no team names, so the one rule SQL can apply is: every row
whose owner team differs from the team that holds it (`team_id`) takes that team. A row whose owner was a different
team the builder chose on purpose (possible for one day before this) is moved to its holding team too; rights and
reviews already went by `team_id`. Rows are rewritten as the table's owner with its row policy set aside for the
statement (`backfill_ddl`). A second run changes nothing. The downgrade restores nothing: the names are not kept.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from ops_store.schema import TEAM_OWNED, TENANT_SCOPED, backfill_ddl

revision = "20261124_0257_skill_owner_ids"
down_revision = "0120_model_call_reservations"
branch_labels = None
depends_on = None

CHAIN = "agents"


def _skills() -> sa.Table:
    """registry_skills as far as its policy needs, as of this revision."""
    return sa.Table(
        "registry_skills",
        sa.MetaData(),
        sa.Column("tenant_id", sa.String(64)),
        sa.Column("team_id", sa.String(64)),
        info={**TENANT_SCOPED, **TEAM_OWNED},
    )


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    before, after = backfill_ddl([_skills()], dialect, chain=CHAIN, kind="team")
    for statement in before:
        op.execute(statement)
    op.execute("UPDATE registry_skills SET owner_team = team_id WHERE owner_team <> team_id")
    for statement in after:
        op.execute(statement)


def downgrade() -> None:
    # Data only, and the names the rows held are gone: the code before this revision reads an owner team id as it reads
    # a name. Rendered as SQL it writes nothing, as the upgrade's rewrite is safe to run again.
    if not op.get_context().as_sql:
        print("20261124_0257_skill_owner_ids: each skill keeps its holding team as its owner team")
