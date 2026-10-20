"""a module version names its review in agents-service's Reviews (c-163)

Revision ID: tools_0019_version_reviews
Revises: tools_0018_secret_teams

Tool module security reviews move out of tools-service into ordinary publish requests. A version keeps the request's
id, when it was asked for, who decided it and, for a no, the reason. `security_reviews` stays until
scripts/copy_tool_reviews.py has moved its rows; tools_0020 drops it.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "tools_0019_version_reviews"
down_revision = "tools_0018_secret_teams"
branch_labels = None
depends_on = None

COLUMNS = (
    sa.Column("review_id", sa.String(64), nullable=True),
    sa.Column("requested_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("reviewer", sa.String(200), nullable=True),
    sa.Column("finding", sa.Text, nullable=True),
)


def upgrade() -> None:
    for c in COLUMNS:
        op.add_column("module_versions", c)


def downgrade() -> None:
    for c in reversed(COLUMNS):
        op.drop_column("module_versions", c.name)
