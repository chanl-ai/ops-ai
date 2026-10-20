"""The tenant's egress allow-list: the only hosts tools-service may reach, for discovery and for calls, and the
private address ranges those hosts may resolve to.

A module does not keep hosts of its own. `module_egress_hosts` names entries of the tenant list, and the foreign key
refuses a host the list does not hold, so a module's hosts and the tenant's list cannot disagree. A host a module
still uses cannot be removed from the list. Every change to hosts or ranges writes an audit row in the same
transaction.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, ClassVar

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from ops_store import Guarantee
from ops_store.search import contains

from .modules import metadata, module_egress_hosts

_TS = sa.DateTime(timezone=True)


def _listed(name: str, key: str, length: int) -> sa.Table:
    return sa.Table(
        name,
        metadata,
        sa.Column("tenant_id", sa.String(64), primary_key=True),
        sa.Column(key, sa.String(length), primary_key=True),
        sa.Column("note", sa.Text, nullable=False),
        sa.Column("added_by", sa.String(200), nullable=False),
        sa.Column("added_at", _TS, nullable=False),
        # The template slot a provisioned record fills, found again by it on the next run, and what a person may change:
        # `system` nothing, `managed` anything (c-180). Null on a record no template made.
        sa.Column("template_id", sa.String(120), index=True),
        sa.Column("protection", sa.String(16)),
    )


# A bare lower-case hostname: no scheme, port or path.
egress_hosts = _listed("egress_hosts", "host", 253)
# A private network in CIDR form; a listed host may resolve into it. Loopback, link-local and cloud metadata are
# never reachable, listed or not.
egress_ranges = _listed("egress_ranges", "cidr", 64)

egress_audit = sa.Table(
    "egress_audit",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("tenant_id", sa.String(64), nullable=False, index=True),
    sa.Column("kind", sa.String(8), nullable=False),
    sa.Column("value", sa.String(253), nullable=False),
    sa.Column("action", sa.String(16), nullable=False),
    sa.Column("actor", sa.String(200), nullable=False),
    sa.Column("at", _TS, nullable=False),
)

TABLES = {"host": (egress_hosts, egress_hosts.c.host), "range": (egress_ranges, egress_ranges.c.cidr)}


class HostInUseError(RuntimeError):
    def __init__(self, host: str, modules: list[str]) -> None:
        super().__init__(host)
        self.host = host
        self.modules = modules


class EgressStore:
    # A change and its audit row land together (TRANSACTION).
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.TRANSACTION})

    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    async def allow_list(self, tenant_id: str) -> dict[str, list[dict[str, Any]]]:
        """Hosts, each with the modules that use it, and ranges."""
        hosts_q = egress_hosts.select().where(egress_hosts.c.tenant_id == tenant_id).order_by(egress_hosts.c.host)
        ranges_q = egress_ranges.select().where(egress_ranges.c.tenant_id == tenant_id).order_by(egress_ranges.c.cidr)
        users_q = sa.select(module_egress_hosts.c.host, module_egress_hosts.c.module_id).where(
            module_egress_hosts.c.tenant_id == tenant_id
        )
        async with self.engine.connect() as c:
            hosts = [dict(r) for r in (await c.execute(hosts_q)).mappings()]
            ranges = [dict(r) for r in (await c.execute(ranges_q)).mappings()]
            used: dict[str, list[str]] = {}
            for host, module_id in await c.execute(users_q):
                used.setdefault(host, []).append(module_id)
        return {"hosts": [{**h, "modules": sorted(used.get(h["host"], []))} for h in hosts], "ranges": ranges}

    async def hosts_page(
        self, tenant_id: str, search: str, offset: int, limit: int, template_id: str | None = None
    ) -> list[dict[str, Any]]:
        """One page of the listed hosts whose name or note contains `search`, by host, each with the modules that use
        it; LIMIT and OFFSET run in the query, and only that page's modules are read."""
        q = (
            egress_hosts.select()
            .where(self._hosts_matching(tenant_id, search, template_id))
            .order_by(sa.func.lower(egress_hosts.c.host))
        )
        async with self.engine.connect() as c:
            hosts = [dict(r) for r in (await c.execute(q.offset(offset).limit(limit))).mappings()]
            users_q = sa.select(module_egress_hosts.c.host, module_egress_hosts.c.module_id).where(
                module_egress_hosts.c.tenant_id == tenant_id, module_egress_hosts.c.host.in_([h["host"] for h in hosts])
            )
            used: dict[str, list[str]] = {}
            for host, module_id in await c.execute(users_q):
                used.setdefault(host, []).append(module_id)
        return [{**h, "modules": sorted(used.get(h["host"], []))} for h in hosts]

    async def hosts_count(self, tenant_id: str, search: str, template_id: str | None = None) -> int:
        q = (
            sa.select(sa.func.count())
            .select_from(egress_hosts)
            .where(self._hosts_matching(tenant_id, search, template_id))
        )
        async with self.engine.connect() as c:
            return int((await c.execute(q)).scalar_one())

    @staticmethod
    def _hosts_matching(tenant_id: str, search: str, template_id: str | None = None) -> sa.ColumnElement[bool]:
        named = sa.or_(contains(egress_hosts.c.host, search), contains(egress_hosts.c.note, search))
        held = sa.and_(egress_hosts.c.tenant_id == tenant_id, named)
        return held if template_id is None else sa.and_(held, egress_hosts.c.template_id == template_id)

    async def protection(self, tenant_id: str, kind: str, value: str) -> str | None:
        """A listed entry's protection (c-180); None when it is unprotected or not listed."""
        table, col = TABLES[kind]
        q = sa.select(table.c.protection).where(table.c.tenant_id == tenant_id, col == value)
        async with self.engine.connect() as c:
            return (await c.execute(q)).scalar_one_or_none()

    async def host_allowed(self, tenant_id: str, host: str) -> bool:
        q = sa.select(sa.literal(1)).where(egress_hosts.c.tenant_id == tenant_id, egress_hosts.c.host == host)
        async with self.engine.connect() as c:
            return (await c.execute(q)).first() is not None

    async def ranges(self, tenant_id: str) -> list[str]:
        q = sa.select(egress_ranges.c.cidr).where(egress_ranges.c.tenant_id == tenant_id)
        async with self.engine.connect() as c:
            return [r[0] for r in await c.execute(q)]

    async def _audit(
        self, c: AsyncConnection, tenant_id: str, change: tuple[str, str, str], *, actor: str, at: datetime
    ) -> None:
        kind, value, action = change
        row = {"tenant_id": tenant_id, "kind": kind, "value": value, "action": action, "actor": actor, "at": at}
        await c.execute(egress_audit.insert().values(**row))

    async def add(
        self,
        tenant_id: str,
        kind: str,
        value: str,
        *,
        actor: str,
        note: str,
        at: datetime,
        template: dict[str, str] | None = None,
    ) -> bool:
        """Adds a host or a range, with the provisioner's `template_id` and `protection` when `template` names them;
        False when it was already listed (nothing written)."""
        table, col = TABLES[kind]
        async with self.engine.begin() as c:
            try:
                async with c.begin_nested():
                    row = {"tenant_id": tenant_id, col.name: value, "note": note, "added_by": actor, "added_at": at}
                    row |= template or {}
                    await c.execute(table.insert().values(**row))
            except IntegrityError:
                return False
            await self._audit(c, tenant_id, (kind, value, "added"), actor=actor, at=at)
        return True

    async def remove(self, tenant_id: str, kind: str, value: str, *, actor: str, at: datetime) -> bool:
        """Removes a host or a range; False when it was not listed. HostInUseError while a module uses the host."""
        table, col = TABLES[kind]
        async with self.engine.begin() as c:
            if kind == "host":
                used = sa.select(module_egress_hosts.c.module_id).where(
                    module_egress_hosts.c.tenant_id == tenant_id, module_egress_hosts.c.host == value
                )
                modules = sorted(r[0] for r in await c.execute(used))
                if modules:
                    raise HostInUseError(value, modules)
            done = await c.execute(table.delete().where(table.c.tenant_id == tenant_id, col == value))
            if done.rowcount == 0:
                return False
            await self._audit(c, tenant_id, (kind, value, "removed"), actor=actor, at=at)
        return True

    async def audit(self, tenant_id: str) -> list[dict[str, Any]]:
        q = egress_audit.select().where(egress_audit.c.tenant_id == tenant_id).order_by(egress_audit.c.id)
        async with self.engine.connect() as c:
            return [dict(r) for r in (await c.execute(q)).mappings()]
