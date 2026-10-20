"""mailboxes: team mailboxes connected on Channels > Email (c-199)

Revision ID: 0047_mailboxes
Revises: 0046_widget_retired

Tenant RLS as on poll_cursors (0045). The mailbox listener finds a live workflow's mailbox outside any request, so
ops_runtime_system (BYPASSRLS) may read the table; it writes nothing there.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0047_mailboxes"
down_revision = "0046_widget_retired"
branch_labels = None
depends_on = None

TENANT_ROLE = "ops_runtime_tenant"
SYSTEM_ROLE = "ops_runtime_system"


def upgrade() -> None:
    op.create_table(
        "mailboxes",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("team_id", sa.String(64), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("address", sa.String(320), nullable=False),
        sa.Column("provider", sa.String(16), nullable=False),
        sa.Column("imap_host", sa.String(255)),
        sa.Column("imap_port", sa.Integer()),
        sa.Column("imap_tls", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("username", sa.String(320)),
        sa.Column("password_secret", sa.String(120)),
        sa.Column("graph_tenant_id", sa.String(64)),
        sa.Column("graph_client_id", sa.String(64)),
        sa.Column("folder", sa.String(200), nullable=False, server_default="inbox"),
        sa.Column("paused", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_by", sa.String(320), nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
        sa.UniqueConstraint("tenant_id", "address", name="uq_mailboxes_tenant_address"),
    )
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(f"DO $$ BEGIN CREATE ROLE {TENANT_ROLE} NOLOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END $$")
    op.execute(
        f"DO $$ BEGIN CREATE ROLE {SYSTEM_ROLE} NOLOGIN BYPASSRLS; EXCEPTION WHEN duplicate_object THEN NULL; END $$"
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON mailboxes TO {TENANT_ROLE}")
    op.execute(f"GRANT SELECT ON mailboxes TO {SYSTEM_ROLE}")
    op.execute("ALTER TABLE mailboxes ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE mailboxes FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY mailboxes_tenant ON mailboxes "
        "USING (tenant_id = current_setting('app.tenant_id', true)) "
        "WITH CHECK (tenant_id = current_setting('app.tenant_id', true))"
    )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP POLICY IF EXISTS mailboxes_tenant ON mailboxes")
    op.drop_table("mailboxes")
