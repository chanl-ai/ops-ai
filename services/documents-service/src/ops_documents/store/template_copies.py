# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""Which document types a team installed from a template: one row per copy, in the copy's team, naming the
template's source (`plugin:<plugin id>`), id and version. The copy itself is an ordinary document type made through
the create path; this table is the only place that remembers where it came from, so no type or response changes.

A template has at most one live copy per team, at any version, held by a partial unique index, so a second install
finds the first (two at once: the loser reads the winner's row) and an update moves the row to the next version. A copy
whose type was deleted is marked removed, and the next install makes a new one. A detached copy is the team's own: its
row stays, for the type's own page, and no longer counts, so the template is offered again for a fresh copy.

`base` is the template body the copy was last made or merged against, shaped as a type version reads, with no choices
applied (`ops_service_kit.template_merge`). It is written in the same statement as the row it belongs to and never by a
new version of the type, so a team saving versions of its own cannot move it. agents-service keeps the same table
for its agents, skills and workflows as `template_copies`; every chain's tables share one database, so this one carries
the chain's prefix."""

from __future__ import annotations

from typing import Any, Literal

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_documents.store.metadata import ROLE, metadata
from ops_service_kit.ids import new_id, now_iso
from ops_store import isolation
from ops_store.schema import TENANT_SCOPED, team_owned
from ops_store.team_scope import team_visible

Kind = Literal["document_type"]

template_copies = sa.Table(
    "documents_template_copies",
    metadata,
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("tenant_id", sa.String(64), nullable=False),
    sa.Column("team", sa.String(64), nullable=False),
    sa.Column("kind", sa.String(16), nullable=False),
    sa.Column("record_id", sa.String(200), nullable=False),
    sa.Column("source", sa.String(200), nullable=False),
    sa.Column("template_id", sa.String(200), nullable=False),
    sa.Column("version", sa.Integer, nullable=False),
    # sha256 of the template body the copy was made from, as tools-service answers it: the baseline for changed since.
    sa.Column("digest", sa.String(64)),
    # The type version the copy (or its last update taken) made: a newer version of the type is the team's own edit.
    sa.Column("record_version", sa.Integer),
    # The template body as last merged against (see the module docstring); None on rows made before it was kept.
    sa.Column("base", sa.JSON),
    sa.Column("installed_by", sa.String(320), nullable=False),
    sa.Column("installed_at", sa.String(32), nullable=False),
    sa.Column("removed_at", sa.String(32)),
    sa.Column("detached_at", sa.String(32)),
    sa.Column("detached_by", sa.String(320)),
    info={**TENANT_SCOPED, **team_owned("team")},
)
# A link that still names a type: live, or detached and kept for the type's own page.
KEPT = template_copies.c.removed_at.is_(None)
LIVE = sa.and_(KEPT, template_copies.c.detached_at.is_(None))
# One live copy of a template per team, at any version; a removed or detached copy does not count, so a fresh copy can
# be made. Guarantees one copy follows one template (an update never writes into a second copy).
sa.Index(
    "uq_documents_template_copies_live",
    template_copies.c.tenant_id,
    template_copies.c.team,
    template_copies.c.source,
    template_copies.c.template_id,
    unique=True,
    postgresql_where=LIVE,
    mssql_where=LIVE,
    sqlite_where=LIVE,
)


class TemplateCopies:
    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    async def live(self, source: str, template_id: str) -> dict[str, Any] | None:
        """The acting team's live copy of this template, at whatever version it last took, if it has one."""
        t = template_copies
        q = sa.select(t).where(
            t.c.tenant_id == isolation.tenant(),
            t.c.source == source,
            t.c.template_id == template_id,
            LIVE,
            team_visible(t),
        )
        async with isolation.isolated_tx(self.engine, role=ROLE) as c:
            found = (await c.execute(q)).mappings().first()
        return dict(found) if found is not None else None

    async def of_team(self) -> list[dict[str, Any]]:
        """Every live copy the acting team holds, for the template list's `installed`."""
        t = template_copies
        q = sa.select(t).where(t.c.tenant_id == isolation.tenant(), LIVE, team_visible(t))
        async with isolation.isolated_tx(self.engine, role=ROLE) as c:
            return [dict(r) for r in (await c.execute(q)).mappings()]

    async def add(
        self,
        *,
        team: str,
        kind: Kind,
        record_id: str,
        source: str,
        template_id: str,
        version: int,
        by: str,
        digest: str | None = None,
        record_version: int | None = None,
        base: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], bool]:
        """Records a new copy and answers it with True; when another install of the same template won the race, answers
        that one's row with False. The base goes in the same insert, so the loser's base never lands on the winner's."""
        row = {
            "id": new_id("tcp"),
            "tenant_id": isolation.tenant(),
            "team": team,
            "kind": kind,
            "record_id": record_id,
            "source": source,
            "template_id": template_id,
            "version": version,
            "digest": digest,
            "record_version": record_version,
            "base": base,
            "installed_by": by,
            "installed_at": now_iso(),
        }
        try:
            async with isolation.isolated_tx(self.engine, role=ROLE) as c:
                await c.execute(template_copies.insert().values(**row))
        except IntegrityError:
            first = await self.live(source, template_id)
            if first is None:
                raise
            return first, False
        return {**row, "removed_at": None, "detached_at": None, "detached_by": None}, True

    async def of_record(self, record_id: str) -> dict[str, Any] | None:
        """The acting team's copy row of this type, detached or not, if the type is a copy."""
        t = template_copies
        q = sa.select(t).where(t.c.tenant_id == isolation.tenant(), t.c.record_id == record_id, KEPT, team_visible(t))
        async with isolation.isolated_tx(self.engine, role=ROLE) as c:
            found = (await c.execute(q)).mappings().first()
        return dict(found) if found is not None else None

    async def updated(
        self, copy_id: str, *, version: int, digest: str | None, record_version: int, base: dict[str, Any] | None
    ) -> None:
        """The copy took its template's update: it now stands for that version and body, the type version made, and
        `base` is the template body it was merged against (never the merged result)."""
        t = template_copies
        values = {"version": version, "digest": digest, "record_version": record_version, "base": base}
        async with isolation.isolated_tx(self.engine, role=ROLE) as c:
            await c.execute(
                t.update()
                .where(t.c.tenant_id == isolation.tenant(), t.c.id == copy_id, team_visible(t))
                .values(**values)
            )

    async def detach(self, copy_id: str, *, by: str) -> dict[str, Any]:
        """Makes the copy the team's own: it is offered no update again. A second call answers the same row."""
        t = template_copies
        mine = sa.and_(t.c.tenant_id == isolation.tenant(), t.c.id == copy_id, team_visible(t))
        async with isolation.isolated_tx(self.engine, role=ROLE) as c:
            await c.execute(
                t.update().where(mine, t.c.detached_at.is_(None)).values(detached_at=now_iso(), detached_by=by)
            )
            return dict((await c.execute(sa.select(t).where(mine))).mappings().one())

    async def removed_record(self, record_id: str) -> None:
        """The type a copy made was deleted: its live row, if any, stops counting."""
        t = template_copies
        async with isolation.isolated_tx(self.engine, role=ROLE) as c:
            await c.execute(
                t.update()
                .where(t.c.tenant_id == isolation.tenant(), t.c.record_id == record_id, KEPT, team_visible(t))
                .values(removed_at=now_iso())
            )

    async def removed(self, copy_id: str) -> None:
        """The copy's type is gone: its row stops counting, so the next install makes a new copy."""
        t = template_copies
        async with isolation.isolated_tx(self.engine, role=ROLE) as c:
            await c.execute(
                t.update()
                .where(t.c.tenant_id == isolation.tenant(), t.c.id == copy_id, team_visible(t))
                .values(removed_at=now_iso())
            )
