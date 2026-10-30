"""kb-service's tables, on the shared database under their own migration chain (alembic_version_kb).

A knowledge base belongs to a department team and names its owner; a source brings documents in (file sources only
in this slice, holding file ids, never bytes); a knowledge base reads the sources attached to it. Every row carries
its tenant and its team, and the database holds each transaction to them (kb_0011): every transaction is
`ops_store.isolation.isolated_tx` as `ops_kb_tenant`, and a link, document, version, chunk, change and run take the
team of the base, source or document they belong to.
"""

from __future__ import annotations

from typing import Any, ClassVar

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from ops_service_kit.errors import Conflict
from ops_store import Guarantee, isolation
from ops_store.database import open_database
from ops_store.dialect import db_now
from ops_store.schema import TEAM_OWNED, TENANT_SCOPED
from ops_store.search import contains
from ops_store.team_scope import any_team, team_visible

__all__ = ["ROLE", "SYSTEM_ROLE", "AsyncEngine", "KnowledgeStore", "engine_for", "metadata", "reachable"]

metadata = sa.MetaData()

# The role every kb transaction runs as, which the team policy applies to, and the start-up move's role that reads which
# tenants hold a source (kb_0011).
ROLE = "ops_kb_tenant"
SYSTEM_ROLE = "ops_kb_system"
# The start-up move between file stores reads every tenant's sources before it knows a tenant.
MOVE_TENANTS = "background process: the start-up move between file stores lists the tenants holding a source"

kb_bases = sa.Table(
    "kb_bases",
    metadata,
    sa.Column("tenant_id", sa.String(64), primary_key=True),
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("team_id", sa.String(64), nullable=False),
    sa.Column("name", sa.String(200), nullable=False),
    sa.Column("slug", sa.String(200), nullable=False),
    sa.Column("description", sa.Text, nullable=False),
    sa.Column("color", sa.String(32), nullable=False),
    # Who answers for what the knowledge base serves; required (c-056), so a cited answer always has someone to ask.
    sa.Column("owner", sa.String(200), nullable=False),
    sa.Column("collections", sa.JSON, nullable=False),
    sa.Column("retrieval", sa.JSON, nullable=False),
    sa.Column("created_by", sa.String(200), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("last_refreshed_at", sa.DateTime(timezone=True)),
    # The template the provisioning service made it from, and how the platform protects it (c-180): `system` cannot be
    # changed by a person, `managed` can, and the template's fields come back on the next provisioning run.
    sa.Column("template_id", sa.String(120)),
    sa.Column("protection", sa.String(16)),
    # The base's own documents source, which Add documents adds files to (c-159); found by id, so renaming the base or
    # the source never makes a second one. Null until the first Add documents.
    sa.Column("documents_source_id", sa.String(64)),
    # Name uniqueness per team: two of a team's knowledge bases with one name make a grant ambiguous to the person
    # granting it. Another team's names are not seen (c-507).
    sa.UniqueConstraint("tenant_id", "team_id", "name", name="uq_kb_bases_name"),
    info={**TENANT_SCOPED, **TEAM_OWNED},
)

kb_sources = sa.Table(
    "kb_sources",
    metadata,
    sa.Column("tenant_id", sa.String(64), primary_key=True),
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("team_id", sa.String(64), nullable=False),
    sa.Column("type", sa.String(32), nullable=False),
    sa.Column("name", sa.String(200), nullable=False),
    sa.Column("collection", sa.String(120), nullable=False),
    sa.Column("owner", sa.String(200), nullable=False),
    sa.Column("sensitivity", sa.String(16), nullable=False),
    sa.Column("status", sa.String(16), nullable=False),
    sa.Column("tags", sa.JSON, nullable=False),
    # File ids in files-service; the source never holds bytes.
    sa.Column("file_ids", sa.JSON, nullable=False),
    # The name each file was uploaded under here, by file id: a deduplicated blob keeps its first uploader's name.
    # Set by the application: MySQL 8 refuses a literal default on a JSON column (kb_0005).
    sa.Column("file_names", sa.JSON, nullable=True, default=dict),
    sa.Column("created_by", sa.String(200), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("last_sync_at", sa.DateTime(timezone=True)),
    sa.Column("last_run_status", sa.String(16)),
    # A "tool" source's reading (c-564): plugin, source, its two tools, the connection, the schedule, the watermark and
    # saved cursor of the last sync, and why it is paused; null for a file source.
    sa.Column("config", sa.JSON),
    # Held by the sync running now, so the schedule never starts a second one on the same source.
    sa.Column("lease_until", sa.DateTime(timezone=True)),
    info={**TENANT_SCOPED, **TEAM_OWNED},
)

kb_base_sources = sa.Table(
    "kb_base_sources",
    metadata,
    sa.Column("tenant_id", sa.String(64), primary_key=True),
    sa.Column("team_id", sa.String(64), nullable=False),
    sa.Column("kb_id", sa.String(64), primary_key=True),
    sa.Column("source_id", sa.String(64), primary_key=True),
    sa.ForeignKeyConstraint(
        ["tenant_id", "kb_id"], ["kb_bases.tenant_id", "kb_bases.id"], ondelete="CASCADE", name="fk_kb_link_base"
    ),
    sa.ForeignKeyConstraint(
        ["tenant_id", "source_id"],
        ["kb_sources.tenant_id", "kb_sources.id"],
        ondelete="CASCADE",
        name="fk_kb_link_source",
    ),
    info={**TENANT_SCOPED, **TEAM_OWNED},
)


# A deleted base's id, so a search naming it skips it rather than refusing (agents keep citing their other bases).
kb_retired_bases = sa.Table(
    "kb_retired_bases",
    metadata,
    sa.Column("tenant_id", sa.String(64), primary_key=True),
    sa.Column("team_id", sa.String(64), nullable=False),
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("name", sa.String(200), nullable=False),
    sa.Column("retired_by", sa.String(200), nullable=False),
    sa.Column("retired_at", sa.DateTime(timezone=True), nullable=False),
    info={**TENANT_SCOPED, **TEAM_OWNED},
)

kb_items = sa.Table(
    "kb_items",
    metadata,
    sa.Column("tenant_id", sa.String(64), primary_key=True),
    sa.Column("team_id", sa.String(64), nullable=False),
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("source_id", sa.String(64), nullable=False),
    # One document per name in a source: a file uploaded again under the same name is its next version.
    sa.Column("path", sa.String(400), nullable=False),
    sa.Column("title", sa.String(400), nullable=False),
    sa.Column("mime", sa.String(120), nullable=False),
    sa.Column("size", sa.Integer, nullable=False),
    sa.Column("file_id", sa.String(64), nullable=False),
    sa.Column("digest", sa.String(64), nullable=False),
    sa.Column("version", sa.Integer, nullable=False),
    sa.Column("status", sa.String(16), nullable=False),  # pending | indexed | failed
    sa.Column("error_class", sa.String(32)),
    sa.Column("error", sa.Text),
    # Indexed, with pages left unread (no text layer, or past the page limit), and why.
    sa.Column("warning", sa.Text),
    sa.Column("page_count", sa.Integer),
    sa.Column("chunk_count", sa.Integer, nullable=False),
    sa.Column("owner", sa.String(200), nullable=False),
    # A person confirmed the document is right; who and when, so the claim can be checked.
    sa.Column("verified", sa.Boolean, nullable=False, server_default=sa.false()),
    sa.Column("verified_by", sa.String(200)),
    sa.Column("verified_at", sa.DateTime(timezone=True)),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("processed_at", sa.DateTime(timezone=True)),
    # Read through a connection's tools (c-564): the system's change marker, the item this one is attached to, and its
    # address in the system for a citation.
    sa.Column("marker", sa.String(120)),
    sa.Column("parent_id", sa.String(64)),
    sa.Column("url", sa.Text),
    sa.ForeignKeyConstraint(
        ["tenant_id", "source_id"],
        ["kb_sources.tenant_id", "kb_sources.id"],
        ondelete="CASCADE",
        name="fk_kb_item_source",
    ),
    sa.UniqueConstraint("tenant_id", "source_id", "path", name="uq_kb_items_path"),
    info={**TENANT_SCOPED, **TEAM_OWNED},
)

kb_item_versions = sa.Table(
    "kb_item_versions",
    metadata,
    sa.Column("tenant_id", sa.String(64), primary_key=True),
    sa.Column("team_id", sa.String(64), nullable=False),
    sa.Column("item_id", sa.String(64), primary_key=True),
    sa.Column("version", sa.Integer, primary_key=True),
    sa.Column("file_id", sa.String(64), nullable=False),
    sa.Column("digest", sa.String(64), nullable=False),
    sa.Column("status", sa.String(16), nullable=False),  # current | superseded
    sa.Column("created_by", sa.String(200), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(
        ["tenant_id", "item_id"], ["kb_items.tenant_id", "kb_items.id"], ondelete="CASCADE", name="fk_kb_version_item"
    ),
    info={**TENANT_SCOPED, **TEAM_OWNED},
)

kb_chunks = sa.Table(
    "kb_chunks",
    metadata,
    sa.Column("tenant_id", sa.String(64), primary_key=True),
    sa.Column("team_id", sa.String(64), nullable=False),
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("item_id", sa.String(64), nullable=False),
    sa.Column("version", sa.Integer, nullable=False),
    sa.Column("position", sa.Integer, nullable=False),
    sa.Column("title", sa.String(400), nullable=False),
    sa.Column("section", sa.String(400), nullable=False),
    sa.Column("page", sa.Integer),
    sa.Column("tokens", sa.Integer, nullable=False),
    sa.Column("text", sa.Text, nullable=False),
    # What full-text search matches: the document title and section path weigh above the body.
    sa.Column(
        "tsv",
        TSVECTOR,
        sa.Computed(
            "setweight(to_tsvector('english', coalesce(title, '') || ' ' || coalesce(section, '')), 'A')"
            " || setweight(to_tsvector('english', text), 'B')",
            persisted=True,
        ),
    ),
    # Set when a newer version replaces the item: a withdrawn chunk is never returned, so no answer cites two versions.
    sa.Column("withdrawn_at", sa.DateTime(timezone=True)),
    sa.ForeignKeyConstraint(
        ["tenant_id", "item_id"], ["kb_items.tenant_id", "kb_items.id"], ondelete="CASCADE", name="fk_kb_chunk_item"
    ),
    sa.Index("ix_kb_chunks_tsv", "tsv", postgresql_using="gin"),
    info={**TENANT_SCOPED, **TEAM_OWNED},
)


kb_changes = sa.Table(
    "kb_changes",
    metadata,
    sa.Column("tenant_id", sa.String(64), primary_key=True),
    sa.Column("team_id", sa.String(64), nullable=False),
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("item_id", sa.String(64), nullable=False),
    sa.Column("source_id", sa.String(64), nullable=False),
    sa.Column("title", sa.String(400), nullable=False),
    sa.Column("section", sa.String(400), nullable=False),
    sa.Column("from_version", sa.Integer, nullable=False),
    sa.Column("to_version", sa.Integer, nullable=False),
    sa.Column("before", sa.Text, nullable=False),
    sa.Column("after", sa.Text, nullable=False),
    sa.Column("changed_by", sa.String(200), nullable=False),
    sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
    # No foreign key to the item: the record of who changed what outlives the document's removal.
    sa.Index("ix_kb_changes_at", "tenant_id", "changed_at"),
    info={**TENANT_SCOPED, **TEAM_OWNED},
)


kb_runs = sa.Table(
    "kb_runs",
    metadata,
    sa.Column("tenant_id", sa.String(64), primary_key=True),
    sa.Column("team_id", sa.String(64), nullable=False),
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("source_id", sa.String(64), nullable=False),
    sa.Column("trigger", sa.String(16), nullable=False),  # manual | full | retry
    sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("duration_sec", sa.Float(), nullable=False),
    sa.Column("status", sa.String(16), nullable=False),
    sa.Column("counts", sa.JSON, nullable=False),
    sa.Column("errors", sa.JSON, nullable=False),
    sa.Column("log", sa.JSON, nullable=False),
    sa.Column("started_by", sa.String(200), nullable=False),
    sa.ForeignKeyConstraint(
        ["tenant_id", "source_id"],
        ["kb_sources.tenant_id", "kb_sources.id"],
        ondelete="CASCADE",
        name="fk_kb_run_source",
    ),
    sa.Index("ix_kb_runs_source", "tenant_id", "source_id", "started_at"),
    info={**TENANT_SCOPED, **TEAM_OWNED},
)


class KnowledgeStore:
    """kb-service's door to its knowledge bases and sources, always inside one tenant. Creating a knowledge base with
    its links, attaching sources and removing a source with its links each land whole."""

    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.TRANSACTION})

    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    def _tx(self) -> Any:
        """One transaction carrying the request's (or the task's) tenant and team, as the role the policy applies to."""
        return isolation.isolated_tx(self.engine, role=ROLE)

    @staticmethod
    async def _team_of(c: AsyncConnection, table: sa.Table, tenant: str, row_id: str) -> str:
        """The team of a base, source or document, which the rows written under it take."""
        q = sa.select(table.c.team_id).where(table.c.tenant_id == tenant, table.c.id == row_id, team_visible(table))
        return str((await c.execute(q)).scalar_one())

    async def bases(self, tenant: str) -> list[dict[str, Any]]:
        async with self._tx() as c:
            q = sa.select(kb_bases).where(kb_bases.c.tenant_id == tenant, team_visible(kb_bases))
            rows = (await c.execute(q)).mappings()
            return [dict(r) for r in rows]

    async def taken(self, tenant: str, *, name: str | None = None, kb_id: str | None = None) -> list[dict[str, Any]]:
        """The caller's team's bases holding `name` (any case) or `kb_id`. A name is unique in a team; an id another
        team holds is refused by the insert (`create_base`), without naming that team."""
        t = kb_bases.c
        wanted = [sa.func.lower(t.name) == name.lower()] if name else []
        wanted += [t.id == kb_id] if kb_id else []
        if not wanted:
            return []
        q = sa.select(t.id, t.name).where(t.tenant_id == tenant, sa.or_(*wanted), team_visible(kb_bases))
        async with self._tx() as c:
            return [dict(r) for r in (await c.execute(q)).mappings()]

    async def team_bases(self, tenant: str, team: str | None) -> list[dict[str, Any]]:
        """The bases a person in `team` reads: the team's and those no team owns, as the picker offers (c-222)."""
        t = kb_bases.c
        scope = t.team_id.is_(None) if team is None else sa.or_(t.team_id.is_(None), t.team_id == team)
        async with self._tx() as c:
            rows = (
                await c.execute(sa.select(kb_bases).where(t.tenant_id == tenant, scope, team_visible(kb_bases)))
            ).mappings()
            return [dict(r) for r in rows]

    async def base_options(
        self, tenant: str, team: str | None, *, search: str, offset: int, limit: int, ids: list[str] | None = None
    ) -> list[dict[str, Any]]:
        """Knowledge bases a picker offers, by name: the caller's team's and those no team owns, whose name contains
        `search`, or exactly `ids` when given. LIMIT and OFFSET run in the query."""
        t = kb_bases.c
        scope = t.team_id.is_(None) if team is None else sa.or_(t.team_id.is_(None), t.team_id == team)
        q = sa.select(t.id, t.name, t.description, t.owner).where(t.tenant_id == tenant, scope, team_visible(kb_bases))
        q = q.where(t.id.in_(ids) if ids is not None else contains(t.name, search))
        q = q.order_by(sa.func.lower(t.name), t.id).offset(offset).limit(limit)
        async with self._tx() as c:
            return [dict(r) for r in (await c.execute(q)).mappings()]

    async def base(self, tenant: str, kb_id: str) -> dict[str, Any] | None:
        async with self._tx() as c:
            q = sa.select(kb_bases).where(
                kb_bases.c.tenant_id == tenant, kb_bases.c.id == kb_id, team_visible(kb_bases)
            )
            row = (await c.execute(q)).mappings().first()
            return dict(row) if row else None

    async def tenants(self) -> list[str]:
        """Every tenant holding a source; only the start-up move between file stores reads across tenants."""
        async with isolation.system_tx(self.engine, MOVE_TENANTS, role=SYSTEM_ROLE) as c:
            q = sa.select(kb_sources.c.tenant_id).where(any_team(kb_sources, MOVE_TENANTS))
            return [str(r[0]) for r in await c.execute(q.distinct())]

    async def sources(self, tenant: str, ids: list[str] | None = None) -> list[dict[str, Any]]:
        """Each source with `item_counts`, its documents by status (pending, indexed, failed), so what a source says
        about its documents is what its items are."""
        q = sa.select(kb_sources).where(kb_sources.c.tenant_id == tenant, team_visible(kb_sources))
        if ids is not None:
            q = q.where(kb_sources.c.id.in_(ids))
        counted = (
            sa.select(
                kb_items.c.source_id,
                kb_items.c.status,
                sa.func.count().label("n"),
                sa.func.coalesce(sa.func.sum(kb_items.c.chunk_count), 0).label("chunks"),
            )
            .where(kb_items.c.tenant_id == tenant, team_visible(kb_items))
            .group_by(kb_items.c.source_id, kb_items.c.status)
        )
        if ids is not None:
            counted = counted.where(kb_items.c.source_id.in_(ids))
        async with self._tx() as c:
            rows = [dict(r) for r in (await c.execute(q)).mappings()]
            counts: dict[str, dict[str, int]] = {}
            for r in (await c.execute(counted)).mappings():
                mine = counts.setdefault(str(r["source_id"]), {})
                mine[str(r["status"])] = int(r["n"])
                if r["status"] == "indexed":
                    mine["chunks"] = int(r["chunks"])
        return [{**r, "item_counts": counts.get(r["id"], {})} for r in rows]

    async def links(self, tenant: str) -> list[tuple[str, str]]:
        """(knowledge base id, source id) for every attachment in the tenant."""
        async with self._tx() as c:
            q = sa.select(kb_base_sources.c.kb_id, kb_base_sources.c.source_id).where(
                kb_base_sources.c.tenant_id == tenant, team_visible(kb_base_sources)
            )
            return [(r.kb_id, r.source_id) for r in await c.execute(q)]

    async def create_base(self, row: dict[str, Any], source_ids: list[str]) -> None:
        try:
            async with self._tx() as c:
                await c.execute(sa.insert(kb_bases).values(**row))
                await self._link(c, row["tenant_id"], row["id"], source_ids)
        except IntegrityError as e:
            # An id is unique in the tenant; one another team holds is not seen before the insert.
            raise Conflict(f"A knowledge base with id {row['id']} already exists.") from e

    async def update_base(self, tenant: str, kb_id: str, values: dict[str, Any]) -> None:
        async with self._tx() as c:
            await c.execute(
                sa.update(kb_bases).where(kb_bases.c.tenant_id == tenant, kb_bases.c.id == kb_id).values(**values)
            )

    async def attach(self, tenant: str, kb_id: str, source_ids: list[str]) -> None:
        async with self._tx() as c:
            await self._link(c, tenant, kb_id, source_ids)

    async def _link(self, c: AsyncConnection, tenant: str, kb_id: str, source_ids: list[str]) -> None:
        if not source_ids:
            return
        team = await self._team_of(c, kb_bases, tenant, kb_id)
        stmt = pg_insert(kb_base_sources).values(
            [{"tenant_id": tenant, "team_id": team, "kb_id": kb_id, "source_id": s} for s in source_ids]
        )
        await c.execute(stmt.on_conflict_do_nothing())

    async def create_source(self, row: dict[str, Any], kb_ids: list[str]) -> None:
        async with self._tx() as c:
            await c.execute(sa.insert(kb_sources).values(**row))
            for kb_id in kb_ids:
                await self._link(c, row["tenant_id"], kb_id, [row["id"]])

    async def remove_base(self, tenant: str, kb_id: str, *, by: str) -> bool:
        """Deletes the base and records its id as retired, in one transaction."""
        async with self._tx() as c:
            key = (kb_bases.c.tenant_id == tenant, kb_bases.c.id == kb_id)
            q = sa.select(kb_bases.c.name, kb_bases.c.team_id).where(*key, team_visible(kb_bases))
            row = (await c.execute(q)).first()
            if row is None:
                return False
            await c.execute(sa.delete(kb_bases).where(*key))
            await c.execute(
                sa.insert(kb_retired_bases).values(
                    tenant_id=tenant,
                    team_id=row.team_id,
                    id=kb_id,
                    name=row.name,
                    retired_by=by,
                    retired_at=sa.func.now(),
                )
            )
            return True

    async def retired(self, tenant: str, kb_ids: list[str] | None = None) -> set[str]:
        q = sa.select(kb_retired_bases.c.id).where(
            kb_retired_bases.c.tenant_id == tenant, team_visible(kb_retired_bases)
        )
        if kb_ids is not None:
            q = q.where(kb_retired_bases.c.id.in_(kb_ids))
        async with self._tx() as c:
            return {str(r.id) for r in await c.execute(q)}

    async def remove_source(self, tenant: str, source_id: str) -> bool:
        async with self._tx() as c:
            q = sa.delete(kb_sources).where(kb_sources.c.tenant_id == tenant, kb_sources.c.id == source_id)
            return (await c.execute(q)).rowcount > 0

    # ── Items, versions and chunks ───────────────────────────────────────

    async def items(
        self, tenant: str, *, source_ids: list[str] | None = None, item_id: str | None = None
    ) -> list[dict[str, Any]]:
        q = sa.select(kb_items).where(kb_items.c.tenant_id == tenant, team_visible(kb_items))
        if source_ids is not None:
            q = q.where(kb_items.c.source_id.in_(source_ids))
        if item_id is not None:
            q = q.where(kb_items.c.id == item_id)
        async with self._tx() as c:
            return [dict(r) for r in (await c.execute(q.order_by(kb_items.c.created_at))).mappings()]

    async def versions(self, tenant: str, item_id: str) -> list[dict[str, Any]]:
        q = (
            sa.select(kb_item_versions)
            .where(
                kb_item_versions.c.tenant_id == tenant,
                kb_item_versions.c.item_id == item_id,
                team_visible(kb_item_versions),
            )
            .order_by(kb_item_versions.c.version.desc())
        )
        async with self._tx() as c:
            return [dict(r) for r in (await c.execute(q)).mappings()]

    async def chunks(self, tenant: str, item_id: str) -> list[dict[str, Any]]:
        """The item's live chunks, in reading order."""
        q = (
            sa.select(kb_chunks.c.position, kb_chunks.c.section, kb_chunks.c.page, kb_chunks.c.tokens, kb_chunks.c.text)
            .where(
                kb_chunks.c.tenant_id == tenant,
                kb_chunks.c.item_id == item_id,
                kb_chunks.c.withdrawn_at.is_(None),
                team_visible(kb_chunks),
            )
            .order_by(kb_chunks.c.position)
        )
        async with self._tx() as c:
            return [dict(r) for r in (await c.execute(q)).mappings()]

    async def index_version(
        self,
        tenant: str,
        item: dict[str, Any],
        version: dict[str, Any],
        chunks: list[dict[str, Any]],
        *,
        new: bool,
        change: dict[str, Any] | None = None,
    ) -> int | None:
        """Writes one version of an item with its chunks, and withdraws the previous version's chunks, in one
        transaction: a reader sees the old version or the new one, never both, and the change row lands with the
        version it records. Returns the version it replaced."""
        async with self._tx() as c:
            # The document, its version, chunks and change take its source's team.
            team = await self._team_of(c, kb_sources, tenant, str(item["source_id"]))
            item = {**item, "team_id": team}
            version = {**version, "team_id": team}
            chunks = [{**ch, "team_id": team} for ch in chunks]
            change = {**change, "team_id": team} if change is not None else None
            replaced: int | None = None
            if new:
                await c.execute(sa.insert(kb_items).values(**item))
            else:
                key = (kb_items.c.tenant_id == tenant, kb_items.c.id == item["id"])
                replaced = (
                    await c.execute(sa.select(kb_items.c.version).where(*key, team_visible(kb_items)))
                ).scalar_one()
                await c.execute(sa.update(kb_items).where(*key).values(**item))
                await c.execute(
                    sa.update(kb_item_versions)
                    .where(kb_item_versions.c.tenant_id == tenant, kb_item_versions.c.item_id == item["id"])
                    .values(status="superseded")
                )
                await c.execute(
                    sa.update(kb_chunks)
                    .where(
                        kb_chunks.c.tenant_id == tenant,
                        kb_chunks.c.item_id == item["id"],
                        kb_chunks.c.withdrawn_at.is_(None),
                    )
                    .values(withdrawn_at=sa.func.now())
                )
            await c.execute(sa.insert(kb_item_versions).values(**version))
            if chunks:
                await c.execute(sa.insert(kb_chunks), chunks)
            if change is not None:
                await c.execute(sa.insert(kb_changes).values(**change))
            return replaced

    async def mark_synced(self, tenant: str, source_id: str, status: str, *, activate: bool = False) -> None:
        """Records the run's outcome; `activate` moves a draft source to active in the same statement."""
        values: dict[str, Any] = {"last_sync_at": sa.func.now(), "last_run_status": status}
        if activate:
            values["status"] = sa.case((kb_sources.c.status == "draft", "active"), else_=kb_sources.c.status)
        async with self._tx() as c:
            await c.execute(
                sa.update(kb_sources)
                .where(kb_sources.c.tenant_id == tenant, kb_sources.c.id == source_id)
                .values(**values)
            )

    async def add_file(self, tenant: str, source_id: str, file_id: str, name: str) -> None:
        async with self._tx() as c:
            key = (kb_sources.c.tenant_id == tenant, kb_sources.c.id == source_id)
            row = (
                await c.execute(
                    sa.select(kb_sources.c.file_ids, kb_sources.c.file_names)
                    .where(*key, team_visible(kb_sources))
                    .with_for_update()
                )
            ).one()
            # A file uploaded under a name the source already holds is that document's next version: it takes the
            # earlier file's place, so a sync reads one file per document.
            known: dict[str, str] = dict(row.file_names or {})
            replaced = {f for f, n in known.items() if n == name and f != file_id}
            ids = [f for f in row.file_ids if f not in replaced]
            names = {f: n for f, n in known.items() if f not in replaced} | {file_id: name}
            await c.execute(
                sa.update(kb_sources)
                .where(*key)
                .values(file_ids=ids if file_id in ids else [*ids, file_id], file_names=names)
            )

    async def swap_files(self, tenant: str, source_id: str, moved: dict[str, str]) -> None:
        """Points a source at files copied to another store, keeping each file's place and uploaded name."""
        async with self._tx() as c:
            key = (kb_sources.c.tenant_id == tenant, kb_sources.c.id == source_id)
            row = (
                await c.execute(
                    sa.select(kb_sources.c.file_ids, kb_sources.c.file_names)
                    .where(*key, team_visible(kb_sources))
                    .with_for_update()
                )
            ).one()
            held: list[str] = list(row.file_ids)
            given: dict[str, str] = dict(row.file_names or {})
            ids = [moved.get(f, f) for f in held]
            names = {moved.get(f, f): n for f, n in given.items()}
            await c.execute(sa.update(kb_sources).where(*key).values(file_ids=ids, file_names=names))

    async def drop_files(self, tenant: str, source_id: str, file_ids: set[str]) -> None:
        """Removes files from a source; the stored blobs stay, other sources may hold them."""
        if not file_ids:
            return
        async with self._tx() as c:
            key = (kb_sources.c.tenant_id == tenant, kb_sources.c.id == source_id)
            row = (
                await c.execute(
                    sa.select(kb_sources.c.file_ids, kb_sources.c.file_names)
                    .where(*key, team_visible(kb_sources))
                    .with_for_update()
                )
            ).one()
            kept: list[str] = [f for f in row.file_ids if f not in file_ids]
            names: dict[str, str] = row.file_names or {}
            await c.execute(
                sa.update(kb_sources)
                .where(*key)
                .values(file_ids=kept, file_names={f: n for f, n in names.items() if f in kept})
            )

    async def refreshed(self, tenant: str, kb_ids: list[str]) -> None:
        if not kb_ids:
            return
        async with self._tx() as c:
            await c.execute(
                sa.update(kb_bases)
                .where(kb_bases.c.tenant_id == tenant, kb_bases.c.id.in_(kb_ids))
                .values(last_refreshed_at=sa.func.now())
            )

    async def reindex(self, tenant: str, item_id: str, values: dict[str, Any], chunks: list[dict[str, Any]]) -> None:
        """Rebuilds an item's chunks from the same content, keeping its version: the old chunks are withdrawn in the
        transaction that inserts the new ones."""
        async with self._tx() as c:
            team = await self._team_of(c, kb_items, tenant, item_id)
            chunks = [{**ch, "team_id": team} for ch in chunks]
            await c.execute(
                sa.update(kb_items).where(kb_items.c.tenant_id == tenant, kb_items.c.id == item_id).values(**values)
            )
            await c.execute(
                sa.update(kb_chunks)
                .where(
                    kb_chunks.c.tenant_id == tenant, kb_chunks.c.item_id == item_id, kb_chunks.c.withdrawn_at.is_(None)
                )
                .values(withdrawn_at=sa.func.now())
            )
            if chunks:
                await c.execute(sa.insert(kb_chunks), chunks)

    async def update_item(self, tenant: str, item_id: str, values: dict[str, Any]) -> None:
        async with self._tx() as c:
            await c.execute(
                sa.update(kb_items).where(kb_items.c.tenant_id == tenant, kb_items.c.id == item_id).values(**values)
            )

    async def update_source(self, tenant: str, source_id: str, values: dict[str, Any]) -> None:
        async with self._tx() as c:
            await c.execute(
                sa.update(kb_sources)
                .where(kb_sources.c.tenant_id == tenant, kb_sources.c.id == source_id)
                .values(**values)
            )

    async def detach(self, tenant: str, kb_id: str, source_id: str) -> None:
        async with self._tx() as c:
            await c.execute(
                sa.delete(kb_base_sources).where(
                    kb_base_sources.c.tenant_id == tenant,
                    kb_base_sources.c.kb_id == kb_id,
                    kb_base_sources.c.source_id == source_id,
                )
            )

    async def remove_items(self, tenant: str, item_ids: list[str]) -> int:
        """Drops documents a tool source no longer lists (c-564), with their versions and chunks."""
        if not item_ids:
            return 0
        async with self._tx() as c:
            for table, column in ((kb_chunks, kb_chunks.c.item_id), (kb_item_versions, kb_item_versions.c.item_id)):
                await c.execute(sa.delete(table).where(table.c.tenant_id == tenant, column.in_(item_ids)))
            q = sa.delete(kb_items).where(kb_items.c.tenant_id == tenant, kb_items.c.id.in_(item_ids))
            return (await c.execute(q)).rowcount

    async def claim(self, tenant: str, source_id: str, *, until: Any) -> bool:
        """Takes the source's sync lease until `until` when nobody holds it (or a holder's ran out): true when taken,
        so two syncs of one source never run at once."""
        s = kb_sources
        free = sa.or_(s.c.lease_until.is_(None), s.c.lease_until < db_now())
        async with self._tx() as c:
            q = sa.update(s).where(s.c.tenant_id == tenant, s.c.id == source_id, free).values(lease_until=until)
            return (await c.execute(q)).rowcount == 1

    async def release(self, tenant: str, source_id: str) -> None:
        await self.update_source(tenant, source_id, {"lease_until": None})

    async def add_run(self, row: dict[str, Any]) -> None:
        async with self._tx() as c:
            team = await self._team_of(c, kb_sources, str(row["tenant_id"]), str(row["source_id"]))
            await c.execute(sa.insert(kb_runs).values(**row, team_id=team))

    async def runs(
        self, tenant: str, *, source_id: str | None = None, run_id: str | None = None
    ) -> list[dict[str, Any]]:
        q = sa.select(kb_runs).where(kb_runs.c.tenant_id == tenant, team_visible(kb_runs))
        if source_id is not None:
            q = q.where(kb_runs.c.source_id == source_id)
        if run_id is not None:
            q = q.where(kb_runs.c.id == run_id)
        async with self._tx() as c:
            return [dict(r) for r in (await c.execute(q.order_by(kb_runs.c.started_at.desc()))).mappings()]

    async def changes(self, tenant: str, *, item_ids: list[str] | None = None) -> list[dict[str, Any]]:
        q = sa.select(kb_changes).where(kb_changes.c.tenant_id == tenant, team_visible(kb_changes))
        if item_ids is not None:
            q = q.where(kb_changes.c.item_id.in_(item_ids))
        async with self._tx() as c:
            return [dict(r) for r in (await c.execute(q.order_by(kb_changes.c.changed_at.desc()))).mappings()]


def engine_for(url: str) -> AsyncEngine:
    return open_database(url)


async def reachable(engine: AsyncEngine) -> bool:
    """Whether the database answers; health says degraded when it does not."""
    try:
        async with engine.connect() as c:
            await c.execute(sa.text("SELECT 1"))
    except Exception:
        return False
    return True
