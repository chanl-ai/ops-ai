"""tools-service's service event outbox (c-257)

Revision ID: tools_0026_service_outbox
Revises: tools_0025_access_reviews

A tool access request and a module review are reported as service events (c-258) written in the same transaction
as the change; the relay delivers them to agents-service. The relay reads across tenants, so the table is not under
row-level security.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "tools_0026_service_outbox"
down_revision = "tools_0025_access_reviews"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "service_outbox",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("team_id", sa.String(64), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("event_key", sa.String(200), nullable=False),
        sa.Column("actor", sa.String(320)),
        sa.Column("payload", sa.JSON, nullable=False),
        sa.Column("created_at", sa.Float(asdecimal=False), nullable=False),
        sa.Column("next_at", sa.Float(asdecimal=False)),
        sa.Column("sent_at", sa.Float(asdecimal=False)),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text),
    )
    op.create_index("ix_service_outbox_due", "service_outbox", ["sent_at", "next_at"])


def downgrade() -> None:
    op.drop_index("ix_service_outbox_due", table_name="service_outbox")
    op.drop_table("service_outbox")
