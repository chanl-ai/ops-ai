"""Guardrail names are unique per team

Revision ID: 0102_guardrail_names_per_team
Revises: 0101_skill_names_per_team

A guardrail's slug was unique across every team, so a second team adding the same guardrail was handed a numbered slug
or refused. The key becomes (team_id, slug). This only relaxes a unique key: every stored row already meets the
narrower one, so no row changes. The old key was made inline, so its name differs per database and is read from the
catalogue. Runs on PostgreSQL and SQL Server.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0102_guardrail_names_per_team"
down_revision = "0101_skill_names_per_team"
branch_labels = None
depends_on = None

TABLE = "registry_guardrails"
TEAM_KEY = "uq_registry_guardrails_team_slug"


def _slug_keys() -> list[str]:
    """The names of the unique keys on the slug column alone."""
    found = sa.inspect(op.get_bind()).get_unique_constraints(TABLE)
    return [str(u["name"]) for u in found if u["column_names"] == ["slug"] and u["name"]]


def upgrade() -> None:
    for name in _slug_keys():
        op.drop_constraint(name, TABLE, type_="unique")
    op.create_unique_constraint(TEAM_KEY, TABLE, ["team_id", "slug"])


def downgrade() -> None:
    op.drop_constraint(TEAM_KEY, TABLE, type_="unique")
    op.create_unique_constraint("registry_guardrails_slug_key", TABLE, ["slug"])
