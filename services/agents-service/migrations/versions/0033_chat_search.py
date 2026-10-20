"""chat_search: chat threads' searchable text as plain columns (c-069, portability rule D5)

Revision ID: 0033_chat_search
Revises: 0032_registry_widgets

Search read title, agent name, last reply and questions out of JSON (graph_threads.meta, graph_runs.input), which
MySQL and Azure SQL do not query the same way. These columns are rewritten when a thread is created, renamed or
answered; a thread without a row gets one the next time a list reads it. Tenant RLS as on the run tables (0021).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0033_chat_search"
down_revision = "0032_registry_widgets"
branch_labels = None
depends_on = None

TENANT_ROLE = "ops_runtime_tenant"


def upgrade() -> None:
    op.create_table(
        "chat_search",
        sa.Column("thread_id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False, server_default="local", index=True),
        sa.Column("team_id", sa.String(64), nullable=False, index=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("agent_name", sa.String(200), nullable=False),
        sa.Column("preview", sa.String(400), nullable=False),
        sa.Column("questions", sa.Text, nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute(f"GRANT SELECT, INSERT, DELETE ON chat_search TO {TENANT_ROLE}")
        op.execute("ALTER TABLE chat_search ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE chat_search FORCE ROW LEVEL SECURITY")
        op.execute(
            "CREATE POLICY chat_search_tenant ON chat_search "
            "USING (tenant_id = current_setting('app.tenant_id', true)) "
            "WITH CHECK (tenant_id = current_setting('app.tenant_id', true))"
        )


def downgrade() -> None:
    op.drop_table("chat_search")
