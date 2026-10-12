"""Audit entries written in the same transaction as the change they record (I7).

`record` is what every platform write calls inside its own `tenant_tx`, so the entry and the change commit together or
not at all. `TeamNameAudit` is that mechanism behind ops_store's `AuditPort`, so the shared audit suite can prove it:
renaming a team is the change, and an entry the store refuses (None) fails the rename too.
"""

from __future__ import annotations

from typing import Any, ClassVar

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection

from ops_service_kit.ids import new_id, now_iso
from ops_store import Guarantee

from .tables import audit_entries, teams, tenants
from .tenancy import TenantDb


async def record(
    c: AsyncConnection,
    *,
    tenant_id: str,
    team_id: str | None,
    actor: str,
    action: str,
    target_kind: str,
    target_id: str,
    request_id: str,
    detail: dict[str, Any] | None,
) -> None:
    """One entry, on the caller's connection so it shares the caller's transaction. `detail` must not be None: the
    column refuses null, so a write that cannot say what it did fails as a whole."""
    await c.execute(
        audit_entries.insert().values(
            id=new_id("aud"),
            tenant_id=tenant_id,
            team_id=team_id,
            actor=actor,
            action=action,
            target_kind=target_kind,
            target_id=target_id,
            request_id=request_id,
            at=now_iso(),
            detail=detail,
        )
    )


class TeamNameAudit:
    """Conformance adapter: one tenant and team per entity id, renamed with an audited write."""

    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.TRANSACTION, Guarantee.RLS})

    def __init__(self, db: TenantDb, tenant_id: str) -> None:
        self.db = db
        self.tenant_id = tenant_id

    @classmethod
    async def open(cls, url: str) -> TeamNameAudit:
        db = TenantDb.open(url)
        tenant_id = new_id("ten")
        # The tenants policy keys on the row's own id, so the new tenant is written as itself.
        async with db.tenant_tx(tenant_id) as c:
            await c.execute(
                tenants.insert().values(
                    id=tenant_id, name="conformance", status="active", allowed_domains=[], created_at=now_iso()
                )
            )
        return cls(db, tenant_id)

    async def apply(self, entity_id: str, value: str, entry: dict[str, Any] | None) -> None:
        async with self.db.tenant_tx(self.tenant_id) as c:
            updated = await c.execute(teams.update().where(teams.c.id == entity_id).values(name=value))
            if updated.rowcount == 0:
                await c.execute(
                    teams.insert().values(
                        id=entity_id,
                        tenant_id=self.tenant_id,
                        name=value,
                        owner_groups=[],
                        scope="all",
                        created_at=now_iso(),
                    )
                )
            await record(
                c,
                tenant_id=self.tenant_id,
                team_id=entity_id,
                actor="conformance",
                action="team.rename",
                target_kind="team",
                target_id=entity_id,
                request_id=new_id("req"),
                detail=entry,
            )

    async def value(self, entity_id: str) -> str | None:
        async with self.db.tenant_tx(self.tenant_id) as c:
            return (await c.execute(sa.select(teams.c.name).where(teams.c.id == entity_id))).scalar()

    async def entries(self, entity_id: str) -> int:
        q = sa.select(sa.func.count()).select_from(audit_entries).where(audit_entries.c.target_id == entity_id)
        async with self.db.tenant_tx(self.tenant_id) as c:
            return int((await c.execute(q)).scalar_one())


class AuditLog:
    """Reads entries, newest first. `team_id` None reads every entry in the tenant (a team with scope `all`)."""

    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.RLS})

    def __init__(self, db: TenantDb) -> None:
        self.db = db

    async def page(
        self,
        tenant_id: str,
        team_id: str | None,
        *,
        filters: dict[str, str | None],
        page: int,
        size: int,
    ) -> tuple[list[dict[str, Any]], int]:
        where: list[Any] = []
        if team_id is not None:
            where.append(audit_entries.c.team_id == team_id)
        for column in ("action", "actor", "target_kind"):
            if filters.get(column):
                where.append(audit_entries.c[column] == filters[column])
        if filters.get("from"):
            where.append(audit_entries.c.at >= filters["from"])
        if filters.get("to"):
            where.append(audit_entries.c.at < filters["to"])
        rows = (
            sa.select(audit_entries)
            .where(*where)
            .order_by(audit_entries.c.at.desc(), audit_entries.c.id)
            .limit(size)
            .offset((page - 1) * size)
        )
        total = sa.select(sa.func.count()).select_from(audit_entries).where(*where)
        async with self.db.tenant_tx(tenant_id) as c:
            found = [dict(r) for r in (await c.execute(rows)).mappings().all()]
            count = int((await c.execute(total)).scalar_one())
        return found, count
