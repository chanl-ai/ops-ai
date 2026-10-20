"""operation_mocks: a tool operation's mock answers per environment (c-332)

An operation had one stub, always a success with a JSON body, and calls never used it unless the operation ran on the
stub executor. Mock answers are rows per operation and environment, in order, each a status, body, headers, a delay or
a timeout, optionally matching input values, one of them the default; the executor answers a test call from the first
that matches.

Revision ID: tools_0029_operation_mocks
Revises: tools_0028_connections
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "tools_0029_operation_mocks"
down_revision = "tools_0028_connections"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "operation_mocks",
        sa.Column("tenant_id", sa.String(64), primary_key=True),
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("module_id", sa.String(64), nullable=False),
        sa.Column("operation", sa.String(120), nullable=False),
        sa.Column("environment", sa.String(16), nullable=False),
        sa.Column("position", sa.Integer, nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("match", sa.JSON, nullable=False),
        sa.Column("status", sa.Integer, nullable=False),
        sa.Column("body", sa.JSON),
        sa.Column("headers", sa.JSON, nullable=False),
        sa.Column("delay_ms", sa.Integer, nullable=False),
        sa.Column("timeout", sa.Boolean, nullable=False),
        sa.Column("is_default", sa.Boolean, nullable=False),
        sa.Column("from_call_id", sa.String(64)),
        sa.Column("created_by", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_operation_mocks_operation", "operation_mocks", ["tenant_id", "operation", "environment", "position"]
    )


def downgrade() -> None:
    op.drop_index("ix_operation_mocks_operation", "operation_mocks")
    op.drop_table("operation_mocks")
