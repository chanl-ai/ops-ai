"""The v2 workflows list sorts one team's workflows by name and update time, and finds each one's open request

Revision ID: 0112_definitions_list_indexes
Revises: 0111_cases_list_indexes

The v2 workflows list pages, sorts and counts in SQL: without an index that leads with the name and the update time
after the tenant and team, every page sorts all of the tenant's versions; each row's status asks whether a publish
request of the workflow is pending, which the (kind, subject_id) index cannot seek within one tenant.
"""

from __future__ import annotations

from alembic import op

revision = "0112_definitions_list_indexes"
down_revision = "0111_cases_list_indexes"
branch_labels = None
depends_on = None

INDEXES = {
    "ix_engine_definitions_team_name": ("engine_definitions", ["tenant_id", "team_id", "name"]),
    "ix_engine_definitions_team_created": ("engine_definitions", ["tenant_id", "team_id", "created_at"]),
    "ix_registry_publish_requests_tenant_subject": ("registry_publish_requests", ["tenant_id", "subject_id"]),
}


def upgrade() -> None:
    for name, (table, columns) in INDEXES.items():
        op.create_index(name, table, columns)


def downgrade() -> None:
    for name, (table, _) in INDEXES.items():
        op.drop_index(name, table_name=table)
