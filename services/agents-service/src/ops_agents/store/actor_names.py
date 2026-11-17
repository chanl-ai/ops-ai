"""The names behind the strings runs and records keep for who did something (api/actors.py): a mailbox's name by its
address, a run's workflow name, an agent's name, an API key's label from this service's copy of the keys. One query per
kind for a whole page."""

from __future__ import annotations

from typing import ClassVar

import sqlalchemy as sa

from ops_engine.store.tables import engine_definitions, engine_runs
from ops_store import Guarantee
from ops_store.team_scope import team_visible

from .agent_registry import registry_agent_versions, registry_agents
from .api_key_copies import api_key_copies
from .form_links import form_links
from .mailboxes import mailboxes
from .tenancy import RuntimeStore, current_tenant

# What a run of a workflow version with no name is called where people read it: never its id.
UNNAMED_WORKFLOW = "a workflow run"
FORM = "form:"


class ActorNames(RuntimeStore):
    requires: ClassVar[frozenset[Guarantee]] = frozenset()

    async def names(
        self, *, addresses: set[str], run_ids: set[str], agent_ids: set[str], key_ids: frozenset[str] = frozenset()
    ) -> dict[tuple[str, str], str]:
        """`{(kind, id): name}` for kinds trigger (by mailbox address), run, agent and key; what is not found is left
        out. A revoked key keeps its copy row, so a run a retired key started keeps the key's name."""
        names: dict[tuple[str, str], str] = {}
        async with self.tx() as c:
            if addresses:
                m = mailboxes
                q = sa.select(m.c.address, m.c.name).where(
                    m.c.tenant_id == current_tenant(), m.c.address.in_(addresses), team_visible(m)
                )
                names |= {("trigger", str(a)): str(n) for a, n in (await c.execute(q)).all()}
                # A hosted form's link run (`trigger:form:<id>`) is named by the form's title.
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
            if key_ids:
                k = api_key_copies
                q = sa.select(k.c.id, k.c.name).where(
                    k.c.tenant_id == current_tenant(), k.c.id.in_(key_ids), team_visible(k)
                )
                names |= {("key", str(i)): str(n) for i, n in (await c.execute(q)).all()}
        if agent_ids:
            a, v = registry_agents, registry_agent_versions
            q = (
                sa.select(a.c.id, v.c.spec["name"].as_string())
                .select_from(a.join(v, sa.and_(v.c.agent_id == a.c.id, v.c.version == a.c.version)))
                .where(a.c.id.in_(agent_ids), team_visible(a))
            )
            async with self.tx() as c:
                names |= {("agent", str(i)): str(n) for i, n in (await c.execute(q)).all() if n}
        return names
