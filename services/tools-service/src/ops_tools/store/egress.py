"""The tenant's egress allow-list: the only hosts tools-service may reach, for discovery and for calls, and the
private address ranges those hosts may resolve to.

A module does not keep hosts of its own. `module_egress_hosts` names entries of the tenant list, and the foreign key
refuses a host the list does not hold, so a module's hosts and the tenant's list cannot disagree. A host a module
still uses cannot be removed from the list. Every change to hosts or ranges writes an audit row in the same
transaction.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import ClassVar

import sqlalchemy as sa
from pydantic import Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from ops_service_kit.http import Out
from ops_service_kit.listing import ListParams
from ops_store import Guarantee, isolation
from ops_store.listing import LISTED, ListPage, list_page
from ops_store.rows import rows
from ops_store.schema import TENANT_SCOPED
from ops_store.store import Store

from .modules import metadata, module_egress_hosts, team_modules, tool_modules
from .tenancy import ROLE

# Why the allow-list is read and written across the tenant's teams: it is the tenant's one list, never a team's, and
# its callers include start-up and the gateway's connect check, which name the tenant and no team.
ALLOW_LIST = "the egress allow-list is the tenant's, not a team's"

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
        # `system` nothing, `managed` anything. Null on a record no template made.
        sa.Column("template_id", sa.String(120), index=True, info=LISTED),
        sa.Column("protection", sa.String(16)),
        info=TENANT_SCOPED,
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
    info=TENANT_SCOPED,
)

TABLES = {"host": (egress_hosts, egress_hosts.c.host), "range": (egress_ranges, egress_ranges.c.cidr)}


class ModuleUse(Out):
    """A module whose endpoint is on a listed host, by id and the name a person knows it by."""

    id: str
    name: str


class _Listed(Out):
    tenant_id: str
    note: str
    added_by: str
    added_at: datetime
    template_id: str | None
    protection: str | None


class ListedHost(_Listed):
    host: str
    # Filled after the host is read: the modules that use it, by name.
    modules: list[ModuleUse] = Field(default_factory=list[ModuleUse])


class ListedRange(_Listed):
    cidr: str


class AllowList(Out):
    hosts: list[ListedHost]
    ranges: list[ListedRange]


class EgressChange(Out):
    """One audit row: a host or range added or removed, by whom and when."""

    id: int
    tenant_id: str
    kind: str
    value: str
    action: str
    actor: str
    at: datetime


def _by_name(modules: list[ModuleUse]) -> list[ModuleUse]:
    return sorted(modules, key=lambda m: m.name.lower())


def _users(tenant_id: str) -> sa.Select[str, str, str | None]:
    """Each host's modules with the name a person knows them by, so the allow list never shows a bare module id. A
    module of a team the reader is not acting in keeps its id: its name is that team's record."""
    return (
        sa.select(module_egress_hosts.c.host, module_egress_hosts.c.module_id, tool_modules.c.display_name)
        .outerjoin(
            tool_modules,
            sa.and_(
                tool_modules.c.tenant_id == module_egress_hosts.c.tenant_id,
                tool_modules.c.id == module_egress_hosts.c.module_id,
                team_modules(),
            ),
        )
        .where(module_egress_hosts.c.tenant_id == tenant_id)
    )


class HostInUseError(RuntimeError):
    def __init__(self, host: str, modules: list[str]) -> None:
        super().__init__(host)
        self.host = host
        self.modules = modules


class EgressStore(Store):
    # A change and its audit row land together (TRANSACTION).
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.TRANSACTION})
    role = ROLE

    @asynccontextmanager
    async def _list_tx(self, tenant_id: str) -> AsyncGenerator[AsyncConnection]:
        """The request's transaction, or one of its own, in the tenant whose list it is."""
        with isolation.tenant_wide(ALLOW_LIST, tenant_id=tenant_id):
            async with self.tx() as c:
                yield c

    async def allow_list(self, tenant_id: str) -> AllowList:
        """Hosts, each with the modules that use it, and ranges."""
        hosts_q = egress_hosts.select().where(egress_hosts.c.tenant_id == tenant_id).order_by(egress_hosts.c.host)
        ranges_q = egress_ranges.select().where(egress_ranges.c.tenant_id == tenant_id).order_by(egress_ranges.c.cidr)
        users_q = _users(tenant_id)
        async with self._list_tx(tenant_id) as c:
            hosts = await rows(c, hosts_q, ListedHost)
            ranges = await rows(c, ranges_q, ListedRange)
            used: dict[str, list[ModuleUse]] = {}
            for host, module_id, name in await c.execute(users_q):
                used.setdefault(host, []).append(ModuleUse(id=module_id, name=name or module_id))
        return AllowList(hosts=[_using(h, used) for h in hosts], ranges=ranges)

    async def host_page(self, tenant_id: str, params: ListParams) -> tuple[ListPage, list[ListedHost]]:
        """One page of the listed hosts, by host name and then the key, searched by host or note and filtered by the
        template slot (`templateId`), each with the modules that use it; only that page's modules are read."""
        h = egress_hosts.c
        q = sa.select(*egress_hosts.c).where(h.tenant_id == tenant_id)
        async with self._list_tx(tenant_id) as c:
            page = await list_page(
                c,
                q,
                params,
                search=[h.host, h.note],
                default_sort=sa.func.lower(h.host),
                filters={"templateId": h.template_id},
            )
            hosts = [ListedHost.model_validate(r) for r in page["data"]]
            return page, await self._with_modules(c, tenant_id, hosts)

    async def entry(self, tenant_id: str, kind: str, value: str) -> ListedHost | ListedRange | None:
        """One listed host, with the modules that use it, or one listed range, in the shape the lists return; None
        when it is not listed. An add returns it, so a screen can show the new row wherever its list is paged."""
        if kind == "host":
            q = egress_hosts.select().where(egress_hosts.c.tenant_id == tenant_id, egress_hosts.c.host == value)
            async with self._list_tx(tenant_id) as c:
                found = await self._with_modules(c, tenant_id, await rows(c, q, ListedHost))
            return found[0] if found else None
        q = egress_ranges.select().where(egress_ranges.c.tenant_id == tenant_id, egress_ranges.c.cidr == value)
        async with self._list_tx(tenant_id) as c:
            ranges = await rows(c, q, ListedRange)
        return ranges[0] if ranges else None

    @staticmethod
    async def _with_modules(c: AsyncConnection, tenant_id: str, hosts: list[ListedHost]) -> list[ListedHost]:
        """`hosts`, each with the modules that use it; only these hosts' modules are read."""
        users_q = _users(tenant_id).where(module_egress_hosts.c.host.in_([h.host for h in hosts]))
        used: dict[str, list[ModuleUse]] = {}
        for host, module_id, name in await c.execute(users_q):
            used.setdefault(host, []).append(ModuleUse(id=module_id, name=name or module_id))
        return [_using(h, used) for h in hosts]

    async def protection(self, tenant_id: str, kind: str, value: str) -> str | None:
        """A listed entry's protection; None when it is unprotected or not listed."""
        table, col = TABLES[kind]
        q = sa.select(table.c.protection).where(table.c.tenant_id == tenant_id, col == value)
        async with self._list_tx(tenant_id) as c:
            return (await c.execute(q)).scalar_one_or_none()

    async def host_allowed(self, tenant_id: str, host: str) -> bool:
        q = sa.select(sa.literal(1)).where(egress_hosts.c.tenant_id == tenant_id, egress_hosts.c.host == host)
        async with self._list_tx(tenant_id) as c:
            return (await c.execute(q)).first() is not None

    async def ranges(self, tenant_id: str) -> list[str]:
        q = sa.select(egress_ranges.c.cidr).where(egress_ranges.c.tenant_id == tenant_id)
        async with self._list_tx(tenant_id) as c:
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
        async with self._list_tx(tenant_id) as c:
            try:
                async with self.attempt(c):
                    row = {"tenant_id": tenant_id, col.name: value, "note": note, "added_by": actor, "added_at": at}
                    row |= template or {}
                    await c.execute(table.insert().values(**row))
            except IntegrityError:
                return False
            await self._audit(c, tenant_id, (kind, value, "added"), actor=actor, at=at)
        return True

    async def reword(self, tenant_id: str, *, was: tuple[str, str], now: tuple[str, str]) -> int:
        """Hosts added by `was` (actor, note) take `now` instead; the hosts and their audit entries are unchanged."""
        q = (
            egress_hosts.update()
            .where(
                egress_hosts.c.tenant_id == tenant_id,
                egress_hosts.c.added_by == was[0],
                egress_hosts.c.note == was[1],
            )
            .values(added_by=now[0], note=now[1])
        )
        async with self._list_tx(tenant_id) as c:
            return (await c.execute(q)).rowcount

    async def remove(self, tenant_id: str, kind: str, value: str, *, actor: str, at: datetime) -> bool:
        """Removes a host or a range; False when it was not listed. HostInUseError while a module uses the host."""
        table, col = TABLES[kind]
        async with self._list_tx(tenant_id) as c:
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

    async def audit(self, tenant_id: str) -> list[EgressChange]:
        q = egress_audit.select().where(egress_audit.c.tenant_id == tenant_id).order_by(egress_audit.c.id)
        async with self._list_tx(tenant_id) as c:
            return await rows(c, q, EgressChange)


def _using(host: ListedHost, used: dict[str, list[ModuleUse]]) -> ListedHost:
    return host.model_copy(update={"modules": _by_name(used.get(host.host, []))})
