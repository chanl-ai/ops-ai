"""A tool module name is unique per team, not per tenant (c-509)

Revision ID: tools_0034_tools_per_team
Revises: tools_0033_operation_code

Two teams in one tenant each hold their own copy of a module (sharing is installing a copy). The tenant-wide
unique keys on tool_modules.name and module_operations.name refused the second copy with 409. Names become unique
per team for modules, and per module for operations so search_customers can exist in each team's bank copy.

This upgrade only changes the keys. It does not copy rows: a database that already holds modules keeps them, and
the seed writes each module inside that team's scope. The full per-team copy (T002) is a later migration.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "tools_0034_tools_per_team"
down_revision = "tools_0033_operation_code"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ux_tool_modules_name", "tool_modules", type_="unique")
    op.create_index(
        "ux_tool_modules_name",
        "tool_modules",
        ["tenant_id", "team_id", "name"],
        unique=True,
        postgresql_where=sa.text("team_id IS NOT NULL"),
        mssql_where=sa.text("team_id IS NOT NULL"),
    )
    op.create_index(
        "ux_tool_modules_shared_name",
        "tool_modules",
        ["tenant_id", "name"],
        unique=True,
        postgresql_where=sa.text("team_id IS NULL"),
        mssql_where=sa.text("team_id IS NULL"),
    )
    op.drop_constraint("ux_module_operations_name", "module_operations", type_="unique")
    op.create_unique_constraint("ux_module_operations_name", "module_operations", ["tenant_id", "module_id", "name"])


def downgrade() -> None:
    op.drop_constraint("ux_module_operations_name", "module_operations", type_="unique")
    op.create_unique_constraint("ux_module_operations_name", "module_operations", ["tenant_id", "name"])
    op.drop_index("ux_tool_modules_shared_name", table_name="tool_modules")
    op.drop_index("ux_tool_modules_name", table_name="tool_modules")
    op.create_unique_constraint("ux_tool_modules_name", "tool_modules", ["tenant_id", "name"])
