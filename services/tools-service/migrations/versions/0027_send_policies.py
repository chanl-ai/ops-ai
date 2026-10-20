"""send_policies, send_checks: a team's sending policy and the gateway's judgements of writes against it (c-300)

A write left the gateway with nothing reading it against the team's own rules. With the team's checkBeforeSend on,
the gateway judges each write's payload against the newest policy version and keeps the judgement by input hash and
version, so a retry is judged once.

Revision ID: tools_0027_send_policies
Revises: tools_0026_service_outbox
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "tools_0027_send_policies"
down_revision = "tools_0026_service_outbox"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "send_policies",
        sa.Column("tenant_id", sa.String(64), primary_key=True),
        sa.Column("team_id", sa.String(64), primary_key=True),
        sa.Column("version", sa.Integer(), primary_key=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("saved_by", sa.String(320), nullable=False),
        sa.Column("saved_at", sa.String(32), nullable=False),
    )
    op.create_table(
        "send_checks",
        sa.Column("tenant_id", sa.String(64), primary_key=True),
        sa.Column("team_id", sa.String(64), primary_key=True),
        sa.Column("input_hash", sa.String(80), primary_key=True),
        sa.Column("policy_version", sa.Integer(), primary_key=True),
        sa.Column("ok", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("checked_at", sa.String(32), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("send_checks")
    op.drop_table("send_policies")
