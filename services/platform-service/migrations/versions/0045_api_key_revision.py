"""an API key carries a revision every write raises

platform-service now reports each key write as `api_key.changed` (store/key_events.py), and a copy of the keys keeps an
event only over a lower revision, so the key needs one that rises with every write. Existing keys start at 1, the
revision a new key is created at; the column sits on api_keys under its existing grants and row-level security. The
downgrade drops SQL Server's default constraint with the column.

Revision ID: 0045_api_key_revision
Revises: 0044_signin_sp_portable_body
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0045_api_key_revision"
down_revision = "0044_signin_sp_portable_body"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("api_keys") as t:
        t.add_column(sa.Column("revision", sa.Integer, nullable=False, server_default=sa.text("1")))


def downgrade() -> None:
    with op.batch_alter_table("api_keys") as t:
        t.drop_column("revision", mssql_drop_default=True)
