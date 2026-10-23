"""What a case links to, for its assembled page (c-291): its runs with their workflow names, the emails that started
them, and the cases linked to it or open for the same customer. Each list is one
query whatever the case holds, and capped, so a case with many runs reads as fast as one with a few."""

from __future__ import annotations

from typing import Any, ClassVar

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_engine.store.tables import engine_definitions, engine_runs
from ops_store import Guarantee
from ops_store.team_scope import team_visible

from .actor_names import UNNAMED_WORKFLOW
from .cases import case_events, cases
from .tenancy import current_tenant, tenant_tx
from .trigger_events import trigger_events

RUNS_CAP = 30
RELATED_CAP = 5
EMAILS_CAP = 10


class CaseLinks:
    requires: ClassVar[frozenset[Guarantee]] = frozenset()

    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    async def runs(self, case_id: str, team_id: str) -> list[dict[str, Any]]:
        """The runs on the case's timeline, newest first, in the case's team, each with `workflow_name`."""
        e, r, d = case_events, engine_runs, engine_definitions
        named = r.outerjoin(
            d, sa.and_(d.c.tenant_id == r.c.tenant_id, d.c.workflow_id == r.c.workflow_id, d.c.version == r.c.version)
        )
        linked = sa.select(e.c.ref).where(e.c.tenant_id == current_tenant(), e.c.case_id == case_id, e.c.kind == "run")
        q = (
            sa.select(
                *r.c,
                sa.func.coalesce(sa.func.nullif(d.c.name, ""), sa.literal(UNNAMED_WORKFLOW)).label("workflow_name"),
            )
            .select_from(named)
            .where(r.c.tenant_id == current_tenant(), r.c.team_id == team_id, r.c.id.in_(linked))
            .order_by(r.c.created_at.desc(), r.c.id)
            .limit(RUNS_CAP)
        )
        async with tenant_tx(self.engine) as c:
            return [dict(row) for row in (await c.execute(q)).mappings()]

    async def emails(self, run_ids: list[str]) -> list[dict[str, Any]]:
        """The emails that started the runs, newest first."""
        if not run_ids:
            return []
        t = trigger_events
        q = (
            sa.select(t.c.id, t.c.subject, t.c.sender, t.c.recorded_at, t.c.run_id)
            .where(t.c.tenant_id == current_tenant(), t.c.run_id.in_(run_ids), team_visible(t))
            .order_by(t.c.recorded_at.desc(), t.c.id)
            .limit(EMAILS_CAP)
        )
        async with tenant_tx(self.engine) as c:
            return [dict(row) for row in (await c.execute(q)).mappings()]

    async def related(self, case: dict[str, Any]) -> list[dict[str, Any]]:
        """Cases linked to this one, then other cases of the team for the same customer, each with `relation`."""
        k, e = cases, case_events
        linked = sa.select(e.c.ref).where(
            e.c.tenant_id == current_tenant(), e.c.case_id == case["id"], e.c.kind == "link"
        )
        same = k.c.customer_id == case["customer_id"] if case.get("customer_id") else sa.false()
        relation = sa.case((k.c.id.in_(linked), "linked"), else_="same_customer")
        q = (
            sa.select(k.c.id, k.c.subject, k.c.status, relation.label("relation"))
            .where(
                k.c.tenant_id == current_tenant(),
                k.c.team_id == case["team_id"],
                k.c.id != case["id"],
                sa.or_(k.c.id.in_(linked), same),
            )
            .order_by(relation, k.c.created_at.desc(), k.c.id)
            .limit(RELATED_CAP)
        )
        async with tenant_tx(self.engine) as c:
            return [dict(row) for row in (await c.execute(q)).mappings()]
