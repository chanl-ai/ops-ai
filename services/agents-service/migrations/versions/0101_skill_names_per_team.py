"""Skill names are unique per team

Revision ID: 0101_skill_names_per_team
Revises: 0100_copies_base_and_detach

A skill's slug was unique across every team, so the second team to add the same skill template was refused. The key
becomes (team_id, slug). This only relaxes a unique key: every stored row already meets the narrower one, so no row
changes. The old key was made inline, so SQL Server names it and the revision finds it by its column. Runs on
PostgreSQL and SQL Server.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from ops_store.schema import mssql_drop_key_ddl

revision = "0101_skill_names_per_team"
down_revision = "0100_copies_base_and_detach"
branch_labels = None
depends_on = None

TABLE = "registry_skills"
TEAM_KEY = "uq_registry_skills_team_slug"


def _drop_slug_key() -> None:
    """Drops the unique key on the slug column alone. Plain SQL, so the revision also renders as offline SQL."""
    if op.get_bind().dialect.name == "mssql":
        # A key made inline has a generated name on SQL Server, so it is found by its column.
        op.execute(mssql_drop_key_ddl(TABLE, "UQ", "slug"))
    else:
        op.execute(f"ALTER TABLE {TABLE} DROP CONSTRAINT IF EXISTS {TABLE}_slug_key")


def upgrade() -> None:
    _drop_slug_key()
    op.create_unique_constraint(TEAM_KEY, TABLE, ["team_id", "slug"])


def downgrade() -> None:
    # The old key spans every team: a slug two teams hold would make it fail partway. Offline SQL cannot count.
    if not op.get_context().as_sql:
        bind = op.get_bind()
        if bind.dialect.name == "postgresql":
            # The migrating role may own the table; FORCE row-level security would otherwise hide other teams' rows.
            op.execute("SET LOCAL row_security = off")
        t = sa.table(TABLE, sa.column("slug"))
        shared = sa.select(t.c.slug).group_by(t.c.slug).having(sa.func.count() > 1).subquery()
        dupes = bind.execute(sa.select(sa.func.count()).select_from(shared)).scalar_one()
        if dupes:
            raise RuntimeError(
                f"{TABLE}: {dupes} slugs are used by more than one team; rename or remove them before downgrading"
            )
    op.drop_constraint(TEAM_KEY, TABLE, type_="unique")
    op.create_unique_constraint("registry_skills_slug_key", TABLE, ["slug"])
