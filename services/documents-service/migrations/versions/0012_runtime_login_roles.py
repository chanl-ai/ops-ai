"""documents-service's runtime login may switch to the roles documents_0011 made (c-444)

Revision ID: documents_0012
Revises: documents_0011

documents_0011 made ops_documents_tenant (every request transaction) and ops_documents_system (the outbox relay and
the restart's reads) and granted them tables, but made no login a member. roles.sql runs once per server, so a login it
made before those roles existed could not SET ROLE to them: on staging every documents transaction failed. This grants
both to ops_documents_runtime where that login exists; a database whose services connect as the superuser has none,
and nothing changes there.
"""

from __future__ import annotations

from alembic import op

from ops_store.schema import member_ddl

revision = "documents_0012"
down_revision = "documents_0011"
branch_labels = None
depends_on = None

LOGIN = "ops_documents_runtime"
ROLES = ("ops_documents_tenant", "ops_documents_system")


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for role in ROLES:
        op.execute(member_ddl(role, LOGIN))


def downgrade() -> None:
    # The membership stays: roles.sql may have granted it before this revision ran, and taking it away would stop the
    # service at the revision before this one, which needs it too.
    pass
