"""token_person_name: a person's own sign-in keeps the person's name

An app's accounts list shows each person's own sign-in as "Only <name>", and the row held only the person's subject.
The name is kept at sign-in; null for the team's row and for sign-ins made before.

Revision ID: tools_0069_token_person_name
Revises: tools_0068_binding_tools_on
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "tools_0069_token_person_name"
down_revision = "tools_0068_binding_tools_on"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("connection_tokens", sa.Column("person_name", sa.String(200)))


def downgrade() -> None:
    with op.batch_alter_table("connection_tokens") as b:
        b.drop_column("person_name")
