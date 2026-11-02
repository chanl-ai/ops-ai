"""service_outbox for the connection store's role: a broken team account tells admins in the same transaction (c-616)

The gateway marks a team account its system refused, as ops_tools_tenant (tools_0044), and the admins' notice is a
service event in service_outbox. That role could not read or write the outbox, so the mark and its notice could not
commit together. It may now look for an event already written under the notice's key and add one. The outbox holds no
team's secrets and the relay still reads it as the service's own role.

Revision ID: tools_0052_reconnect_notice
Revises: tools_0051_call_team
"""

from __future__ import annotations

from alembic import op

revision = "tools_0052_reconnect_notice"
down_revision = "tools_0051_call_team"
branch_labels = None
depends_on = None

ROLE = "ops_tools_tenant"


def upgrade() -> None:
    if op.get_context().dialect.name == "postgresql":
        op.execute(f"GRANT SELECT, INSERT ON service_outbox TO {ROLE}")


def downgrade() -> None:
    if op.get_context().dialect.name == "postgresql":
        op.execute(f"REVOKE SELECT, INSERT ON service_outbox FROM {ROLE}")
