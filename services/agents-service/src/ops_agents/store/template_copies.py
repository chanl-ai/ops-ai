"""Which records a team installed from a template (c-590): one row per copy, in the copy's team, naming the template's
source (`plugin:<plugin id>`), id and version. The copy itself is an ordinary agent, skill or workflow made through its
create path; this table is the only place that remembers where it came from, so no record or response changes.

A template version has at most one live copy per team, held by a partial unique index, so a second install of the same
version finds the first (two at once: the loser reads the winner's row). A copy whose record was deleted is marked
removed, and the next install makes a new one."""

from __future__ import annotations

from typing import Any, ClassVar, Literal

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_service_kit.ids import new_id, now_iso
from ops_store import Guarantee
from ops_store.schema import TEAM_OWNED, TENANT_SCOPED
from ops_store.team_scope import team_visible

from .base import metadata
from .tenancy import current_tenant, tenant_tx

Kind = Literal["agent", "skill", "workflow"]

template_copies = sa.Table(
    "template_copies",
    metadata,
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("tenant_id", sa.String(64), nullable=False, default=current_tenant),
    sa.Column("team_id", sa.String(64), nullable=False),
    sa.Column("kind", sa.String(16), nullable=False),
    sa.Column("record_id", sa.String(200), nullable=False),
    sa.Column("source", sa.String(200), nullable=False),
    sa.Column("template_id", sa.String(200), nullable=False),
    sa.Column("version", sa.Integer, nullable=False),
    # sha256 of the template body the copy was made from (tools-service's digest): the baseline that tells a copy made
    # from a body the plugin has since changed, even at the same version.
    sa.Column("digest", sa.String(64)),
    sa.Column("installed_by", sa.String(320), nullable=False),
    sa.Column("installed_at", sa.String(32), nullable=False),
    sa.Column("removed_at", sa.String(32)),
    info={**TENANT_SCOPED, **TEAM_OWNED},
)
LIVE = template_copies.c.removed_at.is_(None)
# One live copy of a template version per team; a removed copy does not count, so a reinstall can make a new one.
sa.Index(
    "uq_template_copies_live",
    template_copies.c.tenant_id,
    template_copies.c.team_id,
    template_copies.c.source,
    template_copies.c.template_id,
    template_copies.c.version,
    unique=True,
    postgresql_where=LIVE,
    mssql_where=LIVE,
    sqlite_where=LIVE,
)


class TemplateCopies:
    requires: ClassVar[frozenset[Guarantee]] = frozenset()

    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    async def live(self, source: str, template_id: str, version: int) -> dict[str, Any] | None:
        """The acting team's live copy of this template version, if it has one."""
        t = template_copies
        q = sa.select(t).where(
            t.c.source == source, t.c.template_id == template_id, t.c.version == version, LIVE, team_visible(t)
        )
        async with tenant_tx(self.engine) as c:
            found = (await c.execute(q)).mappings().first()
        return dict(found) if found is not None else None

    async def of_team(self) -> list[dict[str, Any]]:
        """Every live copy the acting team holds, for the template list's `installed`."""
        t = template_copies
        async with tenant_tx(self.engine) as c:
            return [dict(r) for r in (await c.execute(sa.select(t).where(LIVE, team_visible(t)))).mappings()]

    async def add(
        self,
        *,
        team_id: str,
        kind: Kind,
        record_id: str,
        source: str,
        template_id: str,
        version: int,
        by: str,
        digest: str | None = None,
    ) -> tuple[dict[str, Any], bool]:
        """Records a new copy and answers it with True; when another install of the same version won the race, answers
        that one's row with False, and the caller drops the record it made."""
        row = {
            "id": new_id("tcp"),
            "team_id": team_id,
            "kind": kind,
            "record_id": record_id,
            "source": source,
            "template_id": template_id,
            "version": version,
            "digest": digest,
            "installed_by": by,
            "installed_at": now_iso(),
        }
        try:
            async with tenant_tx(self.engine) as c:
                await c.execute(template_copies.insert().values(**row))
        except IntegrityError:
            first = await self.live(source, template_id, version)
            if first is None:
                raise
            return first, False
        return {**row, "tenant_id": current_tenant(), "removed_at": None}, True

    async def removed(self, copy_id: str) -> None:
        """The copy's record is gone: its row stops counting, so the next install makes a new copy."""
        t = template_copies
        async with tenant_tx(self.engine) as c:
            await c.execute(t.update().where(t.c.id == copy_id, team_visible(t)).values(removed_at=now_iso()))

    async def removed_record(self, kind: Kind, record_id: str) -> None:
        """The record a copy made was deleted: its live row, if any, stops counting (called by each delete route)."""
        t = template_copies
        q = t.update().where(t.c.kind == kind, t.c.record_id == record_id, LIVE, team_visible(t))
        async with tenant_tx(self.engine) as c:
            await c.execute(q.values(removed_at=now_iso()))
