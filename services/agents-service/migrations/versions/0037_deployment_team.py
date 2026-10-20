"""team_id on deployments: the team that owns a channel deployment

Revision ID: 0037_deployment_team
Revises: 0036_widget_name

Creating, pausing and polling a deployment is a builder's step in the team that owns it (c-115); with no owner a builder
of any team could pause another team's mailbox. Existing rows get no team, which only an admin changes; the dev seed
writes its team on the next start.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0037_deployment_team"
down_revision = "0036_widget_name"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("deployments") as b:
        b.add_column(sa.Column("team_id", sa.String(64), nullable=False, server_default=""))


def downgrade() -> None:
    with op.batch_alter_table("deployments") as b:
        b.drop_column("team_id")
