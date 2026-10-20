"""teams are created, renamed and archived by workspace admins (c-198)

`status` (`active` or `archived`) and `archived_at` let a team be archived without losing what it owns; an archived team
leaves its members' tokens. `name_key` is the lower-case name under a plain unique index with `tenant_id`, so two teams
of one workspace never share a name in any case, on every database. `template_id` and `protection` are for the
provisioning template (c-175), as the other services' records carry them. Existing rows become active with their name
lower-cased; a name already used in the workspace keeps its shown name and takes its id in its key.

Revision ID: 0013_team_lifecycle
Revises: 0012_system_records
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0013_team_lifecycle"
down_revision = "0012_system_records"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("teams", sa.Column("status", sa.String(16), nullable=False, server_default="active"))
    op.add_column("teams", sa.Column("archived_at", sa.String(40)))
    op.add_column("teams", sa.Column("name_key", sa.String(200)))
    op.add_column("teams", sa.Column("template_id", sa.String(64)))
    op.add_column("teams", sa.Column("protection", sa.String(16), nullable=False, server_default="none"))
    # Two teams of one workspace may already share a name: the first keeps the plain key, each later one takes its id
    # after the name in its key (its shown name is unchanged), so the unique index can be built on every database.
    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id, tenant_id, name FROM teams ORDER BY created_at, id")).all()
    seen: set[tuple[str, str]] = set()
    for team_id, tenant_id, name in rows:
        key = str(name).lower()
        if (tenant_id, key) in seen:
            key = f"{key} {team_id}"
        seen.add((tenant_id, key))
        bind.execute(sa.text("UPDATE teams SET name_key = :k WHERE id = :i"), {"k": key, "i": team_id})
    op.alter_column("teams", "name_key", existing_type=sa.String(200), nullable=False)
    op.create_unique_constraint("uq_teams_tenant_name", "teams", ["tenant_id", "name_key"])


def downgrade() -> None:
    op.drop_constraint("uq_teams_tenant_name", "teams", type_="unique")
    for column in ("protection", "template_id", "name_key", "archived_at", "status"):
        op.drop_column("teams", column)
