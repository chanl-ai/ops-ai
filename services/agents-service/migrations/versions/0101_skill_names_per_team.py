"""Skill names are unique per team

Revision ID: 0101_skill_names_per_team
Revises: 0100_copies_base_and_detach

A skill's slug was unique across every team, so the second team to add the same skill template was refused. The key
becomes (team_id, slug). This only relaxes a unique key: every stored row already meets the narrower one, so no row
changes. The old key was made inline, so its name differs per database and is read from the catalogue. Runs on
PostgreSQL and SQL Server.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0101_skill_names_per_team"
down_revision = "0100_copies_base_and_detach"
branch_labels = None
depends_on = None

TABLE = "registry_skills"
TEAM_KEY = "uq_registry_skills_team_slug"


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
    op.create_unique_constraint("registry_skills_slug_key", TABLE, ["slug"])
