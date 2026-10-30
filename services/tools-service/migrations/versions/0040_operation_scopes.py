"""The scopes an operation needs a person's own sign-in to hold (c-558)

`module_operations.scopes` lists them; a personal token lacking one answers CONNECTION_NOT_LINKED with reason
insufficient_scope and a link asking for the union. `oauth_states.scopes` keeps what a sign-in asked for, which is what
it granted when the system's token answer does not say.

Revision ID: tools_0040_operation_scopes
Revises: tools_0039_module_sign_in
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "tools_0040_operation_scopes"
down_revision = "tools_0039_module_sign_in"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("module_operations", sa.Column("scopes", sa.JSON, nullable=False, server_default="[]"))
    op.add_column("oauth_states", sa.Column("scopes", sa.Text, nullable=False, server_default=""))


def downgrade() -> None:
    op.drop_column("oauth_states", "scopes")
    op.drop_column("module_operations", "scopes")
