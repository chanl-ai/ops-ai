"""Every workflow definition has a team, except the account's background processes (c-507)

Revision ID: 0075_definitions_have_a_team
Revises: 0074_types_per_team

A definition with no team was read by every team. The owner's rule is that every record belongs to one team, with the
account's background processes as the one exception (docs/architecture/identity-and-tenancy.md, "The team is the
workspace"): the event workflows and the customer summary stay account-level, and each run they start acts in its
event's team. Every other definition with no team goes to the team that ran it. One that several teams ran stays
with the first and is copied, every version, into each other team under `<id>_<team>`, and that team's runs and
trigger events move to the copy (owner's answer, c-507 interview Q2). One that no team ran is removed. Each move is
printed. A definition's own reference to another workflow (a child-run step) is not rewritten.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import context, op

revision = "0075_definitions_have_a_team"
down_revision = "0074_types_per_team"
branch_labels = None
depends_on = None

# The account's background processes as of this revision, by workflow id.
BACKGROUND = (
    "tool_access_request",
    "system_extract",
    "file_deleted_purge",
    "extraction_corrected_save",
    "api_task",
    "customer_summary",
)

definitions = sa.table("engine_definitions", sa.column("tenant_id"), sa.column("workflow_id"), sa.column("team_id"))
runs = sa.table("engine_runs", sa.column("tenant_id"), sa.column("workflow_id"), sa.column("team_id"))


def _placed() -> sa.ColumnElement[bool]:
    return sa.and_(definitions.c.team_id.is_(None), definitions.c.workflow_id.not_in(BACKGROUND))


def _copy(bind: sa.Connection, tenant: str, workflow: str, team: str) -> str:
    """Every version of `workflow` copied into `team` under a new id; that team's runs and trigger events move to it."""
    copy = f"{workflow}_{team}"[:64]
    full = sa.table(
        "engine_definitions",
        *(
            sa.column(c, sa.String)
            for c in (
                "tenant_id",
                "workflow_id",
                "version",
                "digest",
                "name",
                "definition",
                "created_at",
                "created_by",
                "team_id",
                "stage",
                "archived_at",
                "archived_by",
            )
        ),
    )
    kept = [c for c in full.c if c.name not in ("workflow_id", "team_id")]
    source = sa.select(*kept, sa.literal(copy).label("workflow_id"), sa.literal(team).label("team_id")).where(
        full.c.tenant_id == tenant, full.c.workflow_id == workflow
    )
    bind.execute(full.insert().from_select([*(c.name for c in kept), "workflow_id", "team_id"], source))
    for name in ("engine_runs", "trigger_events"):
        t = sa.table(name, sa.column("tenant_id"), sa.column("workflow_id"), sa.column("team_id"))
        bind.execute(
            sa.update(t)
            .where(t.c.tenant_id == tenant, t.c.workflow_id == workflow, t.c.team_id == team)
            .values(workflow_id=copy)
        )
    return copy


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # The migrating role may own the tables; FORCE row-level security would otherwise hide every row from it.
        op.execute("SET LOCAL row_security = off")
    ran = sa.select(runs.c.team_id).where(
        runs.c.tenant_id == definitions.c.tenant_id, runs.c.workflow_id == definitions.c.workflow_id
    )
    if not context.is_offline_mode():
        users = bind.execute(
            sa.select(definitions.c.tenant_id, definitions.c.workflow_id, runs.c.team_id)
            .select_from(
                definitions.outerjoin(
                    runs,
                    sa.and_(
                        runs.c.tenant_id == definitions.c.tenant_id, runs.c.workflow_id == definitions.c.workflow_id
                    ),
                )
            )
            .where(_placed())
            .distinct()
            .order_by(definitions.c.tenant_id, definitions.c.workflow_id, runs.c.team_id)
        ).all()
        teams: dict[tuple[str, str], list[str]] = {}
        for tenant, workflow, team in users:
            teams.setdefault((tenant, workflow), [])
            if team is not None:
                teams[(tenant, workflow)].append(team)
        for (tenant, workflow), found in teams.items():
            if not found:
                print(f"0075_definitions_have_a_team: removed workflow {workflow} of {tenant}: no team ran it")
            for team in found[1:]:
                copy = _copy(bind, tenant, workflow, team)
                print(f"0075_definitions_have_a_team: copied workflow {workflow} of {tenant} into {team} as {copy}")
    # The first team (in id order) keeps the definition; a DBA's offline script places shared ones by hand first.
    first = ran.order_by(runs.c.team_id).limit(1).scalar_subquery()
    op.execute(sa.update(definitions).where(_placed()).values(team_id=first))
    op.execute(sa.delete(definitions).where(_placed()))


def downgrade() -> None:
    """Nothing to undo: each definition keeps the team it was given, and removed ones are not restored."""
