"""Template copies keep their merge base and can be detached

Revision ID: 0100_copies_base_and_detach
Revises: 0099_review_asker_is_person

A copy link stores the template body it was last made or merged against (`base`), so an update can tell the team's
edits from the template's changes field by field, and records a detach (`detached_at`, `detached_by`), after which the
copy is the team's own and is offered no update. One live copy per template and team, at any version: a link moves to
the next version when its update is taken, so a second Add after a pin moves finds the first copy. Older duplicate live
rows (one per version before) are marked removed, keeping the newest, before the narrower unique index is made. All
columns are nullable: links made before carry no base and read as having none. Runs on PostgreSQL and SQL Server.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0100_copies_base_and_detach"
down_revision = "0099_review_asker_is_person"
branch_labels = None
depends_on = None

LIVE = sa.text("removed_at IS NULL AND detached_at IS NULL")
OLD_LIVE = sa.text("removed_at IS NULL")
# A live row with a newer live row of the same template in its team is a leftover of the per-version index.
SUPERSEDED = """
UPDATE template_copies SET removed_at = :at
WHERE removed_at IS NULL AND EXISTS (
    SELECT 1 FROM template_copies n
    WHERE n.tenant_id = template_copies.tenant_id AND n.team_id = template_copies.team_id
      AND n.source = template_copies.source AND n.template_id = template_copies.template_id
      AND n.removed_at IS NULL
      AND (n.version > template_copies.version
           OR (n.version = template_copies.version AND n.installed_at > template_copies.installed_at)
           OR (n.version = template_copies.version AND n.installed_at = template_copies.installed_at
               AND n.id > template_copies.id))
)
"""


def upgrade() -> None:
    with op.batch_alter_table("template_copies") as b:
        b.add_column(sa.Column("base", sa.JSON()))
        b.add_column(sa.Column("detached_at", sa.String(32)))
        b.add_column(sa.Column("detached_by", sa.String(320)))
    op.execute(sa.text(SUPERSEDED).bindparams(at="2026-11-10T00:00:00+00:00"))
    op.drop_index("uq_template_copies_live", table_name="template_copies")
    op.create_index(
        "uq_template_copies_live",
        "template_copies",
        ["tenant_id", "team_id", "source", "template_id"],
        unique=True,
        postgresql_where=LIVE,
        mssql_where=LIVE,
    )


def downgrade() -> None:
    # The per-version index counts a detached copy as live, so a detached row stops counting before it is made.
    op.execute(
        sa.text(
            "UPDATE template_copies SET removed_at = detached_at WHERE detached_at IS NOT NULL AND removed_at IS NULL"
        )
    )
    op.drop_index("uq_template_copies_live", table_name="template_copies")
    op.create_index(
        "uq_template_copies_live",
        "template_copies",
        ["tenant_id", "team_id", "source", "template_id", "version"],
        unique=True,
        postgresql_where=OLD_LIVE,
        mssql_where=OLD_LIVE,
    )
    with op.batch_alter_table("template_copies") as b:
        b.drop_column("detached_by")
        b.drop_column("detached_at")
        b.drop_column("base")
