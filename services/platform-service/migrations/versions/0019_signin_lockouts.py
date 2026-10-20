"""wrong passwords are counted per person and lock sign-in after too many

One row per person who has typed a wrong password recently (c-196): how many in the current window, when the window
began, and until when the person is locked. Sign-in and step-up both count here. The row carries tenant_id under the
same row-level security as 0001; it is read after the person, and so the tenant, is known.

Revision ID: 0019_signin_lockouts
Revises: 0018_admin_chat_all
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0019_signin_lockouts"
down_revision = "0018_admin_chat_all"
branch_labels = None
depends_on = None

TENANT = "ops_platform_tenant"


def upgrade() -> None:
    op.create_table(
        "signin_lockouts",
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id"), primary_key=True),
        sa.Column("user_id", sa.String(64), primary_key=True),
        sa.Column("failures", sa.Integer, nullable=False),
        sa.Column("first_failed_at", sa.String(40), nullable=False),
        sa.Column("locked_until", sa.String(40)),
        sa.ForeignKeyConstraint(
            ["tenant_id", "user_id"], ["users.tenant_id", "users.id"], name="fk_signin_lockouts_user"
        ),
    )
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON signin_lockouts TO {TENANT}")
    op.execute("ALTER TABLE signin_lockouts ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE signin_lockouts FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY signin_lockouts_tenant ON signin_lockouts "
        "USING (tenant_id = current_setting('app.tenant_id', true)) "
        "WITH CHECK (tenant_id = current_setting('app.tenant_id', true))"
    )


def downgrade() -> None:
    op.drop_table("signin_lockouts")
