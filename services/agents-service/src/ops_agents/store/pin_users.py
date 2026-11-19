"""Batch reads behind the "used by" and "pending review" columns of the registry pages: the acting team's agents'
newest and published versions in one query, and the pending publish requests of a page's records in one query, rather
than one read per agent or per record. The tables are store/agent_registry.py's."""

from __future__ import annotations

from typing import ClassVar

import sqlalchemy as sa
from pydantic import BaseModel, JsonValue

from ops_store import Guarantee
from ops_store.dialect import json_fragment
from ops_store.rows import rows
from ops_store.team_scope import team_visible

from .agent_registry import publish_requests, registry_agent_versions, registry_agents
from .graphs import mine
from .tenancy import RuntimeStore


class HeldVersion(BaseModel):
    """One of an agent's newest or published versions, with its spec."""

    agent_id: str
    slug: str
    version: int
    spec: dict[str, JsonValue]


class AccountVersion(BaseModel):
    """A version of an agent that names accounts (`spec.accounts`, app to account name), any version."""

    agent_id: str
    version: int
    published_version: int | None
    spec: dict[str, JsonValue]


class PendingRequest(BaseModel):
    id: str
    subject_id: str
    version: int
    created_at: str


class PinUsers(RuntimeStore):
    requires: ClassVar[frozenset[Guarantee]] = frozenset()

    async def held_versions(self, team_id: str | None = None) -> list[HeldVersion]:
        """The newest and the published version of each agent the acting team sees in the caller's tenant (one row
        when they are the same version), only `team_id`'s agents when given, by agent then version. The tenant and
        team are named in the query as well as by the row policies."""
        a, v = registry_agents, registry_agent_versions
        held = sa.or_(v.c.version == a.c.version, v.c.version == a.c.published_version)
        q = (
            sa.select(v.c.agent_id, a.c.slug, v.c.version, v.c.spec)
            .join(a, sa.and_(a.c.id == v.c.agent_id, a.c.tenant_id == v.c.tenant_id))
            .where(mine(a), held, team_visible(a), team_visible(v))
            .order_by(v.c.agent_id, v.c.version)
        )
        if team_id is not None:
            q = q.where(a.c.team_id == team_id)
        async with self.tx() as c:
            return await rows(c, q, HeldVersion)

    async def account_versions(self, team_id: str) -> list[AccountVersion]:
        """Every version of `team_id`'s agents whose spec names any account, by agent then newest version first; a
        version naming none is not read. The tenant and team are named in the query as well as by the row
        policies."""
        a, v = registry_agents, registry_agent_versions
        q = (
            sa.select(v.c.agent_id, v.c.version, a.c.published_version, v.c.spec)
            .join(a, sa.and_(a.c.id == v.c.agent_id, a.c.tenant_id == v.c.tenant_id))
            .where(
                mine(a),
                a.c.team_id == team_id,
                json_fragment(v.c.spec, "accounts").is_not(None),
                team_visible(a),
                team_visible(v),
            )
            .order_by(v.c.agent_id, v.c.version.desc())
        )
        async with self.tx() as c:
            return await rows(c, q, AccountVersion)

    async def pending(self, kind: str, subject_ids: list[str]) -> dict[str, PendingRequest]:
        """The newest pending publish request of each of `subject_ids` (records of `kind`) in the caller's tenant;
        a record with none is left out."""
        if not subject_ids:
            return {}
        r = publish_requests.c
        q = (
            sa.select(r.id, r.subject_id, r.version, r.created_at)
            .where(
                mine(publish_requests),
                r.kind == kind,
                r.status == "pending",
                r.subject_id.in_(sorted(set(subject_ids))),
            )
            .order_by(r.subject_id, r.created_at.desc(), r.id)
        )
        async with self.tx() as c:
            found = await rows(c, q, PendingRequest)
        out: dict[str, PendingRequest] = {}
        for p in found:
            out.setdefault(p.subject_id, p)
        return out
