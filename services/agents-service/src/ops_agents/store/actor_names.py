"""The names behind the strings runs and records keep for who did something (api/actors.py): a mailbox's name by its
address, a run's workflow name, an agent's name. One query per kind for a whole page."""

from __future__ import annotations

from typing import ClassVar

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_engine.store.tables import engine_definitions, engine_runs
from ops_store import Guarantee
from ops_store.team_scope import team_visible

from .agent_registry import registry_agent_versions, registry_agents
from .form_links import form_links
from .mailboxes import mailboxes
from .tenancy import current_tenant, tenant_tx

# What a run of a workflow version with no name is called where people read it: never its id (c-508).
UNNAMED_WORKFLOW = "a workflow run"
FORM = "form:"


class ActorNames:
    requires: ClassVar[frozenset[Guarantee]] = frozenset()

    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    async def names(self, *, addresses: set[str], run_ids: set[str], agent_ids: set[str]) -> dict[tuple[str, str], str]:
        """`{(kind, id): name}` for kinds trigger (by mailbox address), run and agent; what is not found is left out."""
        names: dict[tuple[str, str], str] = {}
        async with tenant_tx(self.engine) as c:
            if addresses:
                m = mailboxes
                q = sa.select(m.c.address, m.c.name).where(
                    m.c.tenant_id == current_tenant(), m.c.address.in_(addresses), team_visible(m)
                )
                names |= {("trigger", str(a)): str(n) for a, n in (await c.execute(q)).all()}
                # A hosted form's link run (`trigger:form:<id>`, c-535) is named by the form's title.
                forms = {a.removeprefix(FORM) for a in addresses if a.startswith(FORM)}
                if forms:
                    f = form_links
                    q = sa.select(f.c.id, f.c.title).where(
                        f.c.tenant_id == current_tenant(), f.c.id.in_(forms), team_visible(f)
                    )
                    names |= {("trigger", f"{FORM}{i}"): str(n) for i, n in (await c.execute(q)).all()}
            if run_ids:
                r, d = engine_runs, engine_definitions
                named = r.outerjoin(
                    d,
                    sa.and_(
                        d.c.tenant_id == r.c.tenant_id, d.c.workflow_id == r.c.workflow_id, d.c.version == r.c.version
                    ),
                )
                q = (
                    sa.select(r.c.id, sa.func.coalesce(sa.func.nullif(d.c.name, ""), sa.literal(UNNAMED_WORKFLOW)))
                    .select_from(named)
                    .where(r.c.tenant_id == current_tenant(), r.c.id.in_(run_ids))
                )
                names |= {("run", str(i)): str(n) for i, n in (await c.execute(q)).all()}
        if agent_ids:
            # The registry is not a tenant table: the tenant role cannot read it, so it is read on its own connection,
            # as the registry store reads it.
            a, v = registry_agents, registry_agent_versions
            q = (
                sa.select(a.c.id, v.c.spec["name"].as_string())
                .select_from(a.join(v, sa.and_(v.c.agent_id == a.c.id, v.c.version == a.c.version)))
                .where(a.c.id.in_(agent_ids))
            )
            async with self.engine.connect() as c:
                names |= {("agent", str(i)): str(n) for i, n in (await c.execute(q)).all() if n}
        return names
