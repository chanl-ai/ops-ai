"""Document type copies keep their merge base and can be detached

Revision ID: documents_0018
Revises: documents_0017

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

revision = "documents_0018"
down_revision = "documents_0017"
branch_labels = None
depends_on = None

TABLE = "documents_template_copies"
INDEX = "uq_documents_template_copies_live"
LIVE = sa.text("removed_at IS NULL AND detached_at IS NULL")
OLD_LIVE = sa.text("removed_at IS NULL")
# A live row with a newer live row of the same template in its team is a leftover of the per-version index.
SUPERSEDED = f"""
UPDATE {TABLE} SET removed_at = :at
WHERE removed_at IS NULL AND EXISTS (
    SELECT 1 FROM {TABLE} n
    WHERE n.tenant_id = {TABLE}.tenant_id AND n.team = {TABLE}.team
      AND n.source = {TABLE}.source AND n.template_id = {TABLE}.template_id
      AND n.removed_at IS NULL
      AND (n.version > {TABLE}.version
           OR (n.version = {TABLE}.version AND n.installed_at > {TABLE}.installed_at)
           OR (n.version = {TABLE}.version AND n.installed_at = {TABLE}.installed_at AND n.id > {TABLE}.id))
)
"""


def upgrade() -> None:
    with op.batch_alter_table(TABLE) as b:
        b.add_column(sa.Column("base", sa.JSON()))
        b.add_column(sa.Column("detached_at", sa.String(32)))
        b.add_column(sa.Column("detached_by", sa.String(320)))
    op.execute(sa.text(SUPERSEDED).bindparams(at="2026-11-10T00:00:00+00:00"))
    op.drop_index(INDEX, table_name=TABLE)
    op.create_index(
        INDEX,
        TABLE,
        ["tenant_id", "team", "source", "template_id"],
        unique=True,
        postgresql_where=LIVE,
        mssql_where=LIVE,
    )


def downgrade() -> None:
    # The per-version index counts a detached copy as live, so a detached row stops counting before it is made.
    op.execute(
        sa.text(f"UPDATE {TABLE} SET removed_at = detached_at WHERE detached_at IS NOT NULL AND removed_at IS NULL")
    )
    op.drop_index(INDEX, table_name=TABLE)
    op.create_index(
        INDEX,
        TABLE,
        ["tenant_id", "team", "source", "template_id", "version"],
        unique=True,
        postgresql_where=OLD_LIVE,
        mssql_where=OLD_LIVE,
    )
    with op.batch_alter_table(TABLE) as b:
        b.drop_column("detached_by")
        b.drop_column("detached_at")
        b.drop_column("base")
