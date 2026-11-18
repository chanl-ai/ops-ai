"""roles indexed by built-in or custom

The roles list filters on `builtin` in SQL (`ops_store.listing.list_page`), as role pickers ask for custom roles only;
every column a list filters on has an index that leads with it after the tenant. Adds the index; the downgrade drops
it.

Revision ID: 0043_roles_by_builtin
Revises: 0042_sql_server_lookups
"""

from __future__ import annotations

from alembic import op

revision = "0043_roles_by_builtin"
down_revision = "0042_sql_server_lookups"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_roles_builtin", "roles", ["tenant_id", "builtin"])


def downgrade() -> None:
    op.drop_index("ix_roles_builtin", table_name="roles")
