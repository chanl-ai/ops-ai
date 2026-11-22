"""An index for each column the agents lists sort on

The cases, an asset's eval runs and the skills lists honour `sortBy` (ops_store.listing.list_page). Each sortable
column with no index leading with it after the tenant and team gets one here, so a sorted page does not read the
team's whole table. The downgrade drops them.

Revision ID: 20261122_2044_list_sort_indexes
Revises: 0123_eval_run_digest
"""

from __future__ import annotations

from alembic import op

revision = "20261122_2044_list_sort_indexes"
down_revision = "0123_eval_run_digest"
branch_labels = None
depends_on = None

TEAM = ["tenant_id", "team_id"]
INDEXES = (
    ("ix_cases_team_subject", "cases", [*TEAM, "subject"]),
    ("ix_eval_runs_ran_at", "eval_runs", [*TEAM, "ran_at"]),
    ("ix_registry_skills_team_updated", "registry_skills", [*TEAM, "updated_at"]),
)


def upgrade() -> None:
    for name, table, columns in INDEXES:
        op.create_index(name, table, columns)


def downgrade() -> None:
    for name, table, _ in reversed(INDEXES):
        op.drop_index(name, table_name=table)
