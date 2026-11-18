"""Which agents of a team cite which knowledge bases, read in one query: each agent joined to the version it serves
(its published version, else its newest, which a builder testing it sees), kept only when that version's
`collections` names one of the bases asked about. kb-service asks for the bases on one page of its list, so a team
with many agents and bases reads only the rows that page shows."""

from __future__ import annotations

from dataclasses import dataclass

import sqlalchemy as sa
from pydantic import BaseModel, JsonValue

from ops_store.dialect import json_array_has
from ops_store.rows import rows
from ops_store.team_scope import team_visible

from .agent_registry import registry_agent_versions, registry_agents
from .graphs import mine
from .tenancy import RuntimeStore


@dataclass(frozen=True)
class Citation:
    agent_id: str
    name: str
    # The knowledge base ids the served version names, in its order, each once.
    collections: tuple[str, ...]


class _Served(BaseModel):
    id: str
    slug: str
    spec: dict[str, JsonValue]


class KnowledgeCitations(RuntimeStore):
    async def citing(self, team_id: str, kb_ids: list[str] | None) -> list[Citation]:
        """The team's agents whose served version cites any of `kb_ids` (every agent citing anything when None), by
        agent id. The tenant and team are named in the query as well as by the row policies."""
        if kb_ids == []:
            return []
        a, v = registry_agents, registry_agent_versions
        serving = sa.func.coalesce(a.c.published_version, a.c.version)
        q = (
            sa.select(a.c.id, a.c.slug, v.c.spec)
            .join(v, sa.and_(v.c.agent_id == a.c.id, v.c.version == serving, v.c.tenant_id == a.c.tenant_id))
            .where(mine(a), a.c.team_id == team_id, team_visible(a), team_visible(v))
            .order_by(a.c.id)
        )
        if kb_ids is not None:
            q = q.where(sa.or_(*(json_array_has(v.c.spec, "collections", k) for k in sorted(set(kb_ids)))))
        async with self.tx() as c:
            served = await rows(c, q, _Served)
        out: list[Citation] = []
        for r in served:
            named = r.spec.get("collections")
            kbs = tuple(dict.fromkeys(str(k) for k in named)) if isinstance(named, list) else ()
            out.append(Citation(r.id, str(r.spec.get("name") or r.slug), kbs))
        return out
