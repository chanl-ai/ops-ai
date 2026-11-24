"""file_watch_events.code and file_watches.refused_sizes: why a file failed, and said once

A failed event carried only a sentence, so a reader of the events (the Files changed trigger) could not tell a file
too large to bring in, which no retry fixes, from a fetch that may pass next time. `code` holds too_large or
fetch_failed; null for every other kind and for events written before. A file refused for its size with no entry
in Files was a failed event on every full listing; `refused_sizes` ({source id: size}, at most 500 keys, written by
the check's lease holder) lets a check say it again only when the size changes.

Revision ID: 20261125_0900_watch_event_codes
Revises: 20261124_1210_watch_value_names
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261125_0900_watch_event_codes"
down_revision = "20261124_1210_watch_value_names"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("file_watch_events") as b:
        b.add_column(sa.Column("code", sa.String(32)))
    with op.batch_alter_table("file_watches") as b:
        b.add_column(sa.Column("refused_sizes", sa.JSON))


def downgrade() -> None:
    with op.batch_alter_table("file_watches") as b:
        b.drop_column("refused_sizes")
    with op.batch_alter_table("file_watch_events") as b:
        b.drop_column("code")
