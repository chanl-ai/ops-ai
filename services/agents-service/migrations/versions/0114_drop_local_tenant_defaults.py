"""The older thread, review, chat search and widget tables lose their `local` tenant default

Revision ID: 0114_drop_local_tenant_defaults
Revises: 0113_agent_skill_pins

graph_threads, graph_runs, thread_events, review_decisions, review_approvals, chat_search, widget_deployments,
widget_mint_keys and widget_mint_key_audit still gave a row that names no tenant the tenant `local`, so a write that
forgot the caller's tenant landed where another install's dev rows live instead of being refused (0109 did the same
for the registry tables). Every store writes the caller's tenant on each of them (`default=current_tenant` on the
model), so each column keeps NOT NULL and loses its default. On SQL Server Alembic finds the default constraint by its
table and column and drops it. The down path gives each its `local` default back. Runs on PostgreSQL and SQL Server.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0114_drop_local_tenant_defaults"
down_revision = "0113_agent_skill_pins"
branch_labels = None
depends_on = None

LOCAL = "local"
TABLES = (
    "graph_threads",
    "graph_runs",
    "thread_events",
    "review_decisions",
    "review_approvals",
    "chat_search",
    "widget_deployments",
    "widget_mint_keys",
    "widget_mint_key_audit",
)


def upgrade() -> None:
    for name in TABLES:
        op.alter_column(name, "tenant_id", existing_type=sa.String(64), existing_nullable=False, server_default=None)


def downgrade() -> None:
    for name in TABLES:
        op.alter_column(name, "tenant_id", existing_type=sa.String(64), existing_nullable=False, server_default=LOCAL)
