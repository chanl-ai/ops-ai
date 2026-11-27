"""Skill and guardrail names are unique within a tenant's team, not across tenants

Revision ID: 20261127_1000_tenant_slug_keys
Revises: 20261126_2300_drop_model_ledger

Team ids are chosen per tenant, so two tenants can each hold a team with the same id; with the name unique on
(team_id, slug) alone, the second tenant could not save a skill or guardrail of the same name. The unique keys become
(tenant_id, team_id, slug). The down path refuses, with a count, while two tenants hold one (team_id, slug), since the
narrower key would fail partway; offline SQL cannot count. Runs on PostgreSQL and SQL Server.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import context, op

from ops_store.schema import TEAM_OWNED, TENANT_SCOPED, backfill_ddl

revision = "20261127_1000_tenant_slug_keys"
down_revision = "20261126_2300_drop_model_ledger"
branch_labels = None
depends_on = None

CHAIN = "agents"
POLICED = {**TENANT_SCOPED, **TEAM_OWNED}
# Each table and its unique key's name; the key keeps its name across the change.
KEYS = {
    "registry_skills": "uq_registry_skills_team_slug",
    "registry_guardrails": "uq_registry_guardrails_team_slug",
}


def upgrade() -> None:
    for table, name in KEYS.items():
        op.drop_constraint(name, table, type_="unique")
        op.create_unique_constraint(name, table, ["tenant_id", "team_id", "slug"])


def downgrade() -> None:
    if not context.is_offline_mode():
        # The count reads every tenant's rows, so each table's isolation is set aside for it (backfill_ddl).
        policed = [
            sa.Table(
                t,
                sa.MetaData(),
                sa.Column("tenant_id", sa.String(64)),
                sa.Column("team_id", sa.String(64)),
                info=POLICED,
            )
            for t in KEYS
        ]
        before, after = backfill_ddl(policed, op.get_bind().dialect.name, chain=CHAIN)
        for statement in before:
            op.execute(statement)
        for table in KEYS:
            shared = op.get_bind().execute(
                sa.text(
                    f"SELECT COUNT(*) FROM (SELECT team_id, slug FROM {table} GROUP BY team_id, slug "
                    "HAVING COUNT(DISTINCT tenant_id) > 1) d"
                )
            )
            count = int(shared.scalar_one())
            if count:
                raise RuntimeError(f"{table}: {count} team and name pairs are held by more than one tenant")
        for statement in after:
            op.execute(statement)
    for table, name in KEYS.items():
        op.drop_constraint(name, table, type_="unique")
        op.create_unique_constraint(name, table, ["team_id", "slug"])
