"""tool_secrets.ends: the last four characters of a secret's value, so a person can tell which value is held

A secret, and an app credential's client secret, showed only that it was set, so nobody could tell whether the value
held was the one just copied from the system. Its last four characters are now kept beside the reference, written on
every create and rotation; null for a value shorter than eight characters, whose ending would give too much of it
away, and for every value saved before this revision.

Revision ID: tools_0066_secret_ends
Revises: tools_0065_credential_settings
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "tools_0066_secret_ends"
down_revision = "tools_0065_credential_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("tool_secrets") as b:
        b.add_column(sa.Column("ends", sa.String(4)))


def downgrade() -> None:
    with op.batch_alter_table("tool_secrets") as b:
        b.drop_column("ends")
