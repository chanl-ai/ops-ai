"""gateway_calls.team_id: the team each call was made in

The call log carried only its tenant, so Usage could filter only by the modules a team sees, and a call on a shared
module showed in every team's Usage. Each row now records the acting team. Existing rows take their module's team; a
row on no module, or on a shared one, keeps none and is read by nobody (old rows are test data).

Revision ID: tools_0051_call_team
Revises: tools_0050_app_accounts
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "tools_0051_call_team"
down_revision = "tools_0050_app_accounts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("gateway_calls", sa.Column("team_id", sa.String(64)))
    calls = sa.table(
        "gateway_calls",
        sa.column("tenant_id", sa.String),
        sa.column("module_id", sa.String),
        sa.column("team_id", sa.String),
    )
    modules = sa.table(
        "tool_modules", sa.column("tenant_id", sa.String), sa.column("id", sa.String), sa.column("team_id", sa.String)
    )
    owner = (
        sa.select(modules.c.team_id)
        .where(modules.c.tenant_id == calls.c.tenant_id, modules.c.id == calls.c.module_id)
        .limit(1)
        .scalar_subquery()
    )
    # A correlated subquery rather than UPDATE ... FROM, which PostgreSQL and SQL Server write differently.
    op.execute(calls.update().where(calls.c.module_id.isnot(None)).values(team_id=owner))


def downgrade() -> None:
    op.drop_column("gateway_calls", "team_id")
