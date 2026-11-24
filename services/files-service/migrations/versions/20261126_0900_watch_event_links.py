"""file_watch_events.linked_file_id: a file moved or renamed at the source

A source that names a moved or renamed file by a new id (S3 keys are paths) showed it as one removed file and one
new file, with nothing joining them. When exactly one entry removed in a check holds the same bytes as exactly one
new entry of that check, the new event names the removed entry here; null for every other event and those before.

Revision ID: 20261126_0900_watch_event_links
Revises: 20261125_0900_watch_event_codes
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261126_0900_watch_event_links"
down_revision = "20261125_0900_watch_event_codes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("file_watch_events") as b:
        b.add_column(sa.Column("linked_file_id", sa.String(64)))


def downgrade() -> None:
    with op.batch_alter_table("file_watch_events") as b:
        b.drop_column("linked_file_id")
