"""The names behind the strings runs and records keep for who did something (api/actors.py): a mailbox's name by its
address, a run's workflow name, an agent's name. One query per kind for a whole page."""

from __future__ import annotations

from typing import ClassVar

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_engine.store.tables import engine_definitions, engine_runs
from ops_store import Guarantee

from .agent_registry import registry_agent_versions, registry_agents
from .mailboxes import mailboxes
from .tenancy import current_tenant, tenant_tx


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
                    m.c.tenant_id == current_tenant(), m.c.address.in_(addresses)
                )
                names |= {("trigger", str(a)): str(n) for a, n in (await c.execute(q)).all()}
            if run_ids:
                r, d = engine_runs, engine_definitions
                named = r.outerjoin(
                    d,
                    sa.and_(
                        d.c.tenant_id == r.c.tenant_id, d.c.workflow_id == r.c.workflow_id, d.c.version == r.c.version
                    ),
                )
                q = (
                    sa.select(r.c.id, sa.func.coalesce(d.c.name, r.c.workflow_id))
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
