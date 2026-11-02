"""platform_outbox: the events platform-service reports to other services (c-616 S14, on c-258's outbox)

A member removed from a team kept their own accounts on its apps in tools-service, so their tokens worked again if they
came back. platform-service now writes `member.removed` here in the transaction that removes them, and its relay
delivers each event to the services that act on it; platform-service never touches another service's tables. No
row-level security: the relay reads every tenant's due events.

Revision ID: 0027_platform_outbox
Revises: 0026_workspace_owner
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0027_platform_outbox"
down_revision = "0026_workspace_owner"
branch_labels = None
depends_on = None

# The role every request transaction runs as (store/tenancy.py ROLE): it writes an event beside the change.
TENANT = "ops_platform_tenant"


def upgrade() -> None:
    op.create_table(
        "platform_outbox",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("team_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("event_key", sa.String(length=200), nullable=False),
        sa.Column("actor", sa.String(length=320), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.Float(asdecimal=False), nullable=False),
        sa.Column("next_at", sa.Float(asdecimal=False), nullable=True),
        sa.Column("sent_at", sa.Float(asdecimal=False), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_platform_outbox_due", "platform_outbox", ["sent_at", "next_at"])
    if op.get_bind().dialect.name == "postgresql":
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON platform_outbox TO {TENANT}")


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(f"REVOKE ALL ON platform_outbox FROM {TENANT}")
    op.drop_index("ix_platform_outbox_due", table_name="platform_outbox")
    op.drop_table("platform_outbox")
