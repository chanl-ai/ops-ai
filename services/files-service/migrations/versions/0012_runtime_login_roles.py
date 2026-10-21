"""files-service's runtime login may switch to the roles files_0011 made (c-444)

Revision ID: files_0012
Revises: files_0011

files_0011 made ops_files_tenant (every request transaction) and ops_files_system (the outbox relay) and granted them
tables, but made no login a member. roles.sql runs once per server, so a login it made before those roles existed
could not SET ROLE to them: on staging every files transaction failed. This grants both to ops_files_runtime where that
login exists; a database whose services connect as the superuser has none, and nothing changes there.
"""

from __future__ import annotations

from alembic import op

from ops_store.schema import member_ddl

revision = "files_0012"
down_revision = "files_0011"
branch_labels = None
depends_on = None

LOGIN = "ops_files_runtime"
ROLES = ("ops_files_tenant", "ops_files_system")


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for role in ROLES:
        op.execute(member_ddl(role, LOGIN))


def downgrade() -> None:
    # The membership stays: roles.sql may have granted it before this revision ran, and taking it away would stop the
    # service at the revision before this one, which needs it too.
    pass
