"""cases.fields: what a case's producer read or worked out, by name (the levy demo, 2026-10-18)

A workflow could open a case with only a subject, a customer and a priority, so what it read from a document stayed in
the run. An Open or Add to case step's fields are now kept on the case.

Revision ID: 0062_case_fields
Revises: 0061_event_workflows_ordinary
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0062_case_fields"
down_revision = "0061_event_workflows_ordinary"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("cases", sa.Column("fields", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("cases", "fields")
