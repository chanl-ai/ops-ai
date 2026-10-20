"""mailboxes: the sender each mailbox's replies go out through (c-200)

Revision ID: 0050_mailbox_sender
Revises: 0049_mailboxes_no_system_read

`sender` is none, smtp or resend; the sender's password or API key is a Secrets-page secret by name. One column per
step, so MySQL and Azure SQL take the same chain.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0050_mailbox_sender"
down_revision = "0049_mailboxes_no_system_read"
branch_labels = None
depends_on = None

COLUMNS = (
    sa.Column("sender", sa.String(16), nullable=False, server_default="none"),
    sa.Column("from_address", sa.String(320)),
    sa.Column("smtp_host", sa.String(255)),
    sa.Column("smtp_port", sa.Integer()),
    sa.Column("smtp_starttls", sa.Boolean(), nullable=False, server_default=sa.true()),
    sa.Column("sender_secret", sa.String(120)),
)


def upgrade() -> None:
    for column in COLUMNS:
        with op.batch_alter_table("mailboxes") as b:
            b.add_column(column.copy())


def downgrade() -> None:
    for column in reversed(COLUMNS):
        with op.batch_alter_table("mailboxes") as b:
            b.drop_column(column.name)
