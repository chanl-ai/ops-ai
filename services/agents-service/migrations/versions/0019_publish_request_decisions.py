"""publish request decisions: the reason a reviewer gave

Revision ID: 0019_publish_request_decisions
Revises: 0018_workflow_registry
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0019_publish_request_decisions"
down_revision = "0018_workflow_registry"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("registry_publish_requests", sa.Column("decision_reason", sa.Text))


def downgrade() -> None:
    op.drop_column("registry_publish_requests", "decision_reason")
