"""connections: how the platform signs in to a system, per environment, with the tokens a sign-in holds (c-330)

A module's credential was a `{{NAME}}` header row repeated on every operation, and its connection a picture read from
the console seed. A connection is now a record with an auth kind, one row of settings per environment (test,
production) naming the secret rows that hold its secret parts, encrypted tokens, sign-ins in progress and an audit
trail. `tool_secrets.connection_id` marks a secret that belongs to a connection; `gateway_calls` records the
environment and connection a call used.

Revision ID: tools_0028_connections
Revises: tools_0027_send_policies
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "tools_0028_connections"
down_revision = "tools_0027_send_policies"
branch_labels = None
depends_on = None

_TS = sa.DateTime(timezone=True)


def _fk() -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["tenant_id", "connection_id"], ["connections.tenant_id", "connections.id"], ondelete="CASCADE"
    )


def upgrade() -> None:
    op.create_table(
        "connections",
        sa.Column("tenant_id", sa.String(64), primary_key=True),
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("team_id", sa.String(64), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("auth_kind", sa.String(40), nullable=False),
        sa.Column("available_to", sa.JSON),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("status_detail", sa.Text),
        sa.Column("expires_at", _TS),
        sa.Column("catalog_id", sa.String(64)),
        sa.Column("revision", sa.Integer, nullable=False),
        sa.Column("created_by", sa.String(200), nullable=False),
        sa.Column("created_at", _TS, nullable=False),
        sa.Column("updated_by", sa.String(200), nullable=False),
        sa.Column("updated_at", _TS, nullable=False),
    )
    op.create_index("ix_connections_team", "connections", ["tenant_id", "team_id"])
    op.create_table(
        "connection_environments",
        sa.Column("tenant_id", sa.String(64), primary_key=True),
        sa.Column("connection_id", sa.String(64), primary_key=True),
        sa.Column("environment", sa.String(16), primary_key=True),
        sa.Column("settings", sa.JSON, nullable=False),
        sa.Column("secrets", sa.JSON, nullable=False),
        sa.Column("updated_by", sa.String(200), nullable=False),
        sa.Column("updated_at", _TS, nullable=False),
        _fk(),
    )
    op.create_table(
        "connection_tokens",
        sa.Column("tenant_id", sa.String(64), primary_key=True),
        sa.Column("connection_id", sa.String(64), primary_key=True),
        sa.Column("environment", sa.String(16), primary_key=True),
        sa.Column("person_id", sa.String(200), primary_key=True),
        sa.Column("access_ct", sa.Text, nullable=False),
        sa.Column("refresh_ct", sa.Text),
        sa.Column("expires_at", _TS),
        sa.Column("scopes", sa.JSON, nullable=False),
        sa.Column("account", sa.String(320)),
        sa.Column("rotations", sa.Integer, nullable=False),
        sa.Column("refreshed_at", _TS, nullable=False),
        _fk(),
    )
    op.create_table(
        "oauth_states",
        sa.Column("tenant_id", sa.String(64), primary_key=True),
        sa.Column("state_hash", sa.String(64), primary_key=True),
        sa.Column("connection_id", sa.String(64), nullable=False),
        sa.Column("environment", sa.String(16), nullable=False),
        sa.Column("person_id", sa.String(200), nullable=False),
        sa.Column("verifier_ct", sa.Text, nullable=False),
        sa.Column("redirect_uri", sa.Text, nullable=False),
        sa.Column("expires_at", _TS, nullable=False),
        sa.Column("used_at", _TS),
    )
    op.create_table(
        "connection_audit",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("connection_id", sa.String(64), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("environment", sa.String(16)),
        sa.Column("actor", sa.String(200), nullable=False),
        sa.Column("at", _TS, nullable=False),
        sa.Column("detail", sa.JSON, nullable=False),
    )
    op.create_index("ix_connection_audit_connection", "connection_audit", ["tenant_id", "connection_id"])
    op.add_column("tool_secrets", sa.Column("connection_id", sa.String(64)))
    op.add_column("gateway_calls", sa.Column("environment", sa.String(16)))
    op.add_column("gateway_calls", sa.Column("connection_id", sa.String(64)))


def downgrade() -> None:
    op.drop_column("gateway_calls", "connection_id")
    op.drop_column("gateway_calls", "environment")
    op.drop_column("tool_secrets", "connection_id")
    op.drop_index("ix_connection_audit_connection", "connection_audit")
    op.drop_table("connection_audit")
    op.drop_table("oauth_states")
    op.drop_table("connection_tokens")
    op.drop_table("connection_environments")
    op.drop_index("ix_connections_team", "connections")
    op.drop_table("connections")
