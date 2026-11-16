"""The cases list filters one team's cases by status, priority, owner and customer

Revision ID: 0111_cases_list_indexes
Revises: 0110_agents_list_indexes

The cases list pages and filters in SQL; without an index that leads with each filtered column after the tenant and
team, a filtered page reads every case of the team.
"""

from __future__ import annotations

from alembic import op

revision = "0111_cases_list_indexes"
down_revision = "0110_agents_list_indexes"
branch_labels = None
depends_on = None

INDEXES = {
    "ix_cases_team_status": ["tenant_id", "team_id", "status"],
    "ix_cases_team_priority": ["tenant_id", "team_id", "priority"],
    "ix_cases_team_assignee": ["tenant_id", "team_id", "assignee"],
    "ix_cases_team_customer": ["tenant_id", "team_id", "customer_id"],
}


def upgrade() -> None:
    for name, columns in INDEXES.items():
        op.create_index(name, "cases", columns)


def downgrade() -> None:
    for name in INDEXES:
        op.drop_index(name, table_name="cases")
