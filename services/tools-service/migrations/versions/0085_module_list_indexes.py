"""tool_modules: indexes for the Tools list's sort columns

GET /v1/tool-modules chose and sorted every module in Python; it now sorts in SQL by display name, name, owner team or
last update, so each leads an index. Downgrade drops them.

Revision ID: tools_0085_module_list_indexes
Revises: tools_0084_app_cards
"""

from __future__ import annotations

from alembic import op

revision = "tools_0085_module_list_indexes"
down_revision = "tools_0084_app_cards"
branch_labels = None
depends_on = None

INDEXES = {
    "ix_tool_modules_display_name": "display_name",
    "ix_tool_modules_owner_team": "owner_team",
    "ix_tool_modules_updated_at": "updated_at",
    "ix_tool_modules_list_name": "name",
}


def upgrade() -> None:
    for name, column in INDEXES.items():
        op.create_index(name, "tool_modules", [column])


def downgrade() -> None:
    for name in INDEXES:
        op.drop_index(name, table_name="tool_modules")
