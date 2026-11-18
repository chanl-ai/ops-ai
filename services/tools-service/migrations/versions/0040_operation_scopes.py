"""The scopes an operation needs a person's own sign-in to hold

`module_operations.scopes` lists them; a personal token lacking one answers CONNECTION_NOT_LINKED with reason
insufficient_scope and a link asking for the union. `oauth_states.scopes` keeps what a sign-in asked for, which is what
it granted when the system's token answer does not say.

Revision ID: tools_0040_operation_scopes
Revises: tools_0039_module_sign_in
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from ops_store.schema import mssql_drop_default_ddl

revision = "tools_0040_operation_scopes"
down_revision = "tools_0039_module_sign_in"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("module_operations", sa.Column("scopes", sa.JSON, nullable=False, server_default="[]"))
    op.add_column("oauth_states", sa.Column("scopes", sa.Text, nullable=False, server_default=""))


def downgrade() -> None:
    # SQL Server refuses to drop a column that holds a default; the helper drops one only if it is there.
    if op.get_context().dialect.name == "mssql":
        for table, column in (
            ("oauth_states", "scopes"),
            ("module_operations", "scopes"),
        ):
            op.execute(mssql_drop_default_ddl(table, column))
    op.drop_column("oauth_states", "scopes")
    op.drop_column("module_operations", "scopes")
