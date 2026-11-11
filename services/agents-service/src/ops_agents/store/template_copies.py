"""Which records a team installed from a template: one row per copy, in the copy's team, naming the template's
source (`plugin:<plugin id>`), id and version. The copy itself is an ordinary agent, skill or workflow made through its
create path; this table is the only place that remembers where it came from, so no record or response changes.

A template has at most one live copy per team, at any version, held by a partial unique index, so a second install
finds the first (two at once: the loser reads the winner's row) and an update moves the row to the next version. A
copy whose record was deleted is marked removed, and the next install makes a new one. A detached copy is the team's
own: its row stays, for the copy's page, and no longer counts, so the template is offered again for a fresh copy.

`base` is the template body the copy was last made or merged against, with the binding fields left out and no choices
applied (`ops_service_kit.template_merge`). It is written in the same statement as the row it belongs to and never by a
save of the copy, so a team saving over its draft cannot move it."""

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

Kind = Literal["agent", "skill", "workflow", "guardrail", "case_type", "task_type"]

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
    # The digest of the copy's own record as the copy (or its last update) made it: a record whose digest differs now
    # was edited by the team, which an update must not overwrite unseen.
    sa.Column("record_digest", sa.String(64)),
    # The template body as last merged against (see the module docstring); None on rows made before it was kept.
    sa.Column("base", sa.JSON),
    sa.Column("installed_by", sa.String(320), nullable=False),
    sa.Column("installed_at", sa.String(32), nullable=False),
    sa.Column("removed_at", sa.String(32)),
    sa.Column("detached_at", sa.String(32)),
    sa.Column("detached_by", sa.String(320)),
    info={**TENANT_SCOPED, **TEAM_OWNED},
)
# A link that still names a record: live, or detached and kept for the copy's own page.
KEPT = template_copies.c.removed_at.is_(None)
LIVE = sa.and_(KEPT, template_copies.c.detached_at.is_(None))
# One live copy of a template per team, at any version; a removed or detached copy does not count, so a fresh copy
# can be made. Guarantees one copy follows one template (an update never writes into a second copy).
sa.Index(
    "uq_template_copies_live",
    template_copies.c.tenant_id,
    template_copies.c.team_id,
    template_copies.c.source,
    template_copies.c.template_id,
    unique=True,
    postgresql_where=LIVE,
    mssql_where=LIVE,
    sqlite_where=LIVE,
)


class TemplateCopies:
    requires: ClassVar[frozenset[Guarantee]] = frozenset()

    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    async def live(self, source: str, template_id: str) -> dict[str, Any] | None:
        """The acting team's live copy of this template, at whatever version it last took, if it has one."""
        t = template_copies
        q = sa.select(t).where(t.c.source == source, t.c.template_id == template_id, LIVE, team_visible(t))
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
        record_digest: str | None = None,
        base: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], bool]:
        """Records a new copy and answers it with True; when another install of the same template won the race, answers
        that one's row with False, and the caller drops the record it made. The base goes in the same insert, so the
        race loser's base never lands on the winner's row."""
        row = {
            "id": new_id("tcp"),
            "team_id": team_id,
            "kind": kind,
            "record_id": record_id,
            "source": source,
            "template_id": template_id,
            "version": version,
            "digest": digest,
            "record_digest": record_digest,
            "base": base,
            "installed_by": by,
            "installed_at": now_iso(),
        }
        try:
            async with tenant_tx(self.engine) as c:
                await c.execute(template_copies.insert().values(**row))
        except IntegrityError:
            first = await self.live(source, template_id)
            if first is None:
                raise
            return first, False
        return {
            **row,
            "tenant_id": current_tenant(),
            "removed_at": None,
            "detached_at": None,
            "detached_by": None,
        }, True

    async def of_record(self, kind: Kind, record_id: str) -> dict[str, Any] | None:
        """The acting team's copy row of this record, detached or not, if the record is a copy."""
        t = template_copies
        q = sa.select(t).where(t.c.kind == kind, t.c.record_id == record_id, KEPT, team_visible(t))
        async with tenant_tx(self.engine) as c:
            found = (await c.execute(q)).mappings().first()
        return dict(found) if found is not None else None

    async def updated(
        self,
        copy_id: str,
        *,
        version: int,
        digest: str | None,
        record_digest: str | None,
        base: dict[str, Any] | None,
    ) -> None:
        """The copy took its template's update: it now stands for that version and body, and `base` is the template
        body it was merged against (never the merged result)."""
        t = template_copies
        values = {"version": version, "digest": digest, "record_digest": record_digest, "base": base}
        async with tenant_tx(self.engine) as c:
            await c.execute(t.update().where(t.c.id == copy_id, team_visible(t)).values(**values))

    async def detach(self, copy_id: str, *, by: str) -> dict[str, Any]:
        """Makes the copy the team's own: it is offered no update or reset again. A second call answers the same row."""
        t = template_copies
        async with tenant_tx(self.engine) as c:
            await c.execute(
                t.update()
                .where(t.c.id == copy_id, t.c.detached_at.is_(None), team_visible(t))
                .values(detached_at=now_iso(), detached_by=by)
            )
            return dict((await c.execute(sa.select(t).where(t.c.id == copy_id, team_visible(t)))).mappings().one())

    async def removed(self, copy_id: str) -> None:
        """The copy's record is gone: its row stops counting, so the next install makes a new copy."""
        t = template_copies
        async with tenant_tx(self.engine) as c:
            await c.execute(t.update().where(t.c.id == copy_id, team_visible(t)).values(removed_at=now_iso()))

    async def removed_record(self, kind: Kind, record_id: str) -> None:
        """The record a copy made was deleted: its live row, if any, stops counting (called by each delete route)."""
        t = template_copies
        q = t.update().where(t.c.kind == kind, t.c.record_id == record_id, KEPT, team_visible(t))
        async with tenant_tx(self.engine) as c:
            await c.execute(q.values(removed_at=now_iso()))
