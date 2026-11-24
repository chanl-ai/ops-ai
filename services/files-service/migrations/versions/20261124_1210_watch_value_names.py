"""file_watches.value_names: the names the picker showed for a watch's picked folders

A watch keeps its picked sites and libraries as the source's ids, which is what each call is sent, so the Watched
folders list could say only "libraries: 1". The names the picker showed are kept beside them, per input and id. Null
for watches made before and for watches saved without names (the SDK and CLI); the list counts their picked ids.

Revision ID: 20261124_1210_watch_value_names
Revises: 20261124_1200_source_changed_at
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261124_1210_watch_value_names"
down_revision = "20261124_1200_source_changed_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("file_watches") as b:
        b.add_column(sa.Column("value_names", sa.JSON))


def downgrade() -> None:
    with op.batch_alter_table("file_watches") as b:
        b.drop_column("value_names")
