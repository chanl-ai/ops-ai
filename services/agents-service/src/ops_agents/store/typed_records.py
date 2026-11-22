"""Typed records kept as versions (task types and case types), per team.

Every type belongs to one team, keyed (tenant, team, id) so each team holds its own `write_approval`: a seeded
type is the team's copy of a seed file entry, made on its first read; a team's own type only that team reads, edits or
publishes. Every call needs an acting team, since an id alone names one type per team. A save
edits the newest version while it is a draft, or opens the next one on top of a published version; a published version
never changes, so whatever pinned it (a task, a case) keeps reading what it was made with.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Generator
from contextlib import asynccontextmanager, contextmanager
from typing import Any, ClassVar, cast

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from ops_service_kit.errors import Conflict, NotFound
from ops_service_kit.http import Json, Out
from ops_service_kit.ids import now_iso
from ops_service_kit.listing import ListParams
from ops_store import Guarantee
from ops_store.listing import LISTED, ListPage, list_page
from ops_store.rows import one
from ops_store.rows import rows as read_rows
from ops_store.team_scope import acting_as, acting_team, team_visible

from .tenancy import current_tenant, tenant_tx

SEED = "seed"
TEAM = "team"
# `page` sorts on origin and name joined, which orders by origin first only while both are one length.
assert len(SEED) == len(TEAM)


def head_columns() -> list[sa.Column[Any]]:
    """A kind's type table: the type with its newest and newest published version."""
    return [
        sa.Column("tenant_id", sa.String(64), primary_key=True, default=current_tenant),
        sa.Column("team_id", sa.String(64), primary_key=True),
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("origin", sa.String(16), nullable=False),
        sa.Column("name", sa.String(200), nullable=False, info=LISTED),
        sa.Column("description", sa.Text, nullable=False, default=""),
        # Newest saved version, draft or published, and the newest published one.
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("published_version", sa.Integer),
        # The type and version a copy started from.
        sa.Column("copied_from", sa.JSON),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("created_by", sa.String(320), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False, info=LISTED),
        sa.Column("updated_by", sa.String(320), nullable=False),
    ]


def head_indexes(table: str) -> list[sa.Index]:
    """The indexes of a kind's type table: its list sorts by name and by update time (`sortBy`)."""
    return [
        sa.Index(f"ix_{table}_name", "tenant_id", "team_id", "name"),
        sa.Index(f"ix_{table}_updated_at", "tenant_id", "team_id", "updated_at"),
    ]


def version_columns() -> list[sa.Column[Any]]:
    """A kind's version table: every saved version of a type."""
    return [
        sa.Column("tenant_id", sa.String(64), primary_key=True, default=current_tenant),
        sa.Column("team_id", sa.String(64), primary_key=True),
        sa.Column("type_id", sa.String(64), primary_key=True),
        sa.Column("version", sa.Integer, primary_key=True),
        # The record's content and its name and description as they were at this version.
        sa.Column("record", sa.JSON, nullable=False),
        sa.Column("saved_at", sa.String(32), nullable=False),
        sa.Column("saved_by", sa.String(320), nullable=False),
        sa.Column("published_at", sa.String(32)),
        sa.Column("published_by", sa.String(320)),
    ]


class TypeHead(Out):
    """A type's row: its names, its newest and newest published version, and where a copy started."""

    tenant_id: str
    team_id: str
    id: str
    origin: str
    name: str
    description: str
    version: int
    published_version: int | None
    copied_from: Json | None
    created_at: str
    created_by: str
    updated_at: str
    updated_by: str


class TypeVersion(Out):
    """One saved version of a type; `record` is the team-authored definition document."""

    tenant_id: str
    team_id: str
    type_id: str
    version: int
    record: Json
    saved_at: str
    saved_by: str
    published_at: str | None
    published_by: str | None


class TypeDetail(TypeHead):
    """A type with its versions, newest first."""

    versions: list[TypeVersion]


class RecordNotFound(NotFound):
    title: ClassVar[str] = "Type"

    def __init__(self, type_id: str, version: int | None = None) -> None:
        super().__init__(f"{self.title} {type_id}" + (f" v{version}" if version is not None else ""))


class VersionedRecords:
    """One kind of typed record. A subclass names its tables, the keys its record holds and its words."""

    head: ClassVar[sa.Table]
    versions: ClassVar[sa.Table]
    record_keys: ClassVar[tuple[str, ...]]
    noun: ClassVar[str]
    taken_code: ClassVar[str]
    not_found: ClassVar[type[RecordNotFound]]
    # A type id and a version number are unique keys; a save writes its version and moves the type in one transaction.
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.CAS, Guarantee.TRANSACTION})

    def __init__(self, engine: AsyncEngine, team: str | None = None) -> None:
        """`team`: the team whose types this store reads, for a caller serving another team's record (a run's task,
        a case); without it, the acting team."""
        self.engine = engine
        self.team = team

    @contextmanager
    def _in_team(self) -> Generator[str]:
        with acting_as(self.team or acting_team()):
            team = acting_team()
            if team is None:
                raise RuntimeError("typed records are per team; name the team or set the acting team")
            yield team

    @asynccontextmanager
    async def _tx(self) -> AsyncGenerator[tuple[AsyncConnection, str]]:
        """A transaction in the store's team: the one named, or the acting team."""
        with self._in_team() as team:
            async with tenant_tx(self.engine) as c:
                yield c, team

    def record_of(self, content: Json) -> Json:
        return {k: content[k] for k in self.record_keys if k in content}

    async def ensure_seeds(self, seeds: list[Json]) -> None:
        """Each seed in the acting team at its file version, published; a seed whose file version is newer than the
        team's opens that version. The team's own types are never touched."""
        at = now_iso()
        async with self._tx() as (c, team):
            q = sa.select(self.head).where(self.head.c.origin == SEED, team_visible(self.head))
            have = {r.id: r for r in await read_rows(c, q, TypeHead)}
            for s in seeds:
                v = int(cast(int | str, s["version"]))
                row = have.get(str(s["id"]))
                if row is not None and row.version >= v:
                    continue
                version = {
                    "team_id": team,
                    "type_id": s["id"],
                    "version": v,
                    "record": self.record_of(s),
                    "saved_at": at,
                    "saved_by": SEED,
                }
                if row is None:
                    head = {"name": s["name"], "description": s.get("description", "")}
                    await c.execute(
                        self.head.insert().values(
                            id=s["id"],
                            team_id=team,
                            origin=SEED,
                            version=v,
                            published_version=v,
                            created_at=at,
                            created_by=SEED,
                            updated_at=at,
                            updated_by=SEED,
                            **head,
                        )
                    )
                else:
                    await c.execute(
                        self.head.update()
                        .where(self.head.c.id == s["id"], self.head.c.team_id == team)
                        .values(version=v, published_version=v, name=s["name"], updated_at=at, updated_by=SEED)
                    )
                await c.execute(self.versions.insert().values(**version, published_at=at, published_by=SEED))

    async def rows(self) -> list[TypeHead]:
        h = self.head.c
        async with self._tx() as (c, _team):
            q = sa.select(self.head).where(team_visible(self.head)).order_by(h.origin, h.name, h.id)
            return await read_rows(c, q, TypeHead)

    async def page(self, params: ListParams) -> tuple[ListPage, list[TypeHead]]:
        """One page of the team's types on the shared list contract: the seeded ones first, then the team's own, each
        by name, then by id; `search` matches the name and description, `ids` names types (the search is then not
        applied). The page, and its rows as types."""
        h = self.head.c
        async with self._tx() as (c, team):
            q = sa.select(self.head).where(h.tenant_id == current_tenant(), h.team_id == team, team_visible(self.head))
            if params.ids is not None:
                # The key is (tenant, team, id), so the shared `ids` lookup, which needs a one-column key, is done here.
                q = q.where(h.id.in_(params.ids))
                params = params.model_copy(update={"ids": None, "search": None})
            page = await list_page(
                c,
                q,
                params,
                search=[h.name, h.description],
                sortable={"name": h.name, "updatedAt": h.updated_at},
                # Both origins are four letters ("seed", "team"), so origin and name joined sort as origin, then name.
                default_sort=(h.origin + h.name).asc(),
            )
        return page, [TypeHead.model_validate(r) for r in page["data"]]

    async def _row(self, c: AsyncConnection, type_id: str, *, lock: bool = False) -> TypeHead:
        q = sa.select(self.head).where(self.head.c.id == type_id, team_visible(self.head))
        r = await one(c, q.with_for_update() if lock else q, TypeHead)
        if r is None:
            raise self.not_found(type_id)
        return r

    async def get(self, type_id: str) -> TypeDetail:
        """The type with its versions, newest first."""
        async with self._tx() as (c, _team):
            row = await self._row(c, type_id)
            q = (
                sa.select(self.versions)
                .where(self.versions.c.type_id == type_id, team_visible(self.versions))
                .order_by(self.versions.c.version.desc())
            )
            versions = await read_rows(c, q, TypeVersion)
        return TypeDetail(**dict(row), versions=versions)

    async def published(self, type_id: str, version: int | None = None) -> tuple[int, Json]:
        """(version, record) of a published version: the one named, or the newest when None."""
        async with self._tx() as (c, _team):
            row = await self._row(c, type_id)
            n = version if version is not None else row.published_version
            if n is None:
                raise self.not_found(type_id)
            q = sa.select(self.versions).where(
                self.versions.c.type_id == type_id,
                self.versions.c.version == n,
                self.versions.c.published_at.is_not(None),
                team_visible(self.versions),
            )
            v = await one(c, q, TypeVersion)
        if v is None:
            raise self.not_found(type_id, n)
        return n, v.record

    async def create(self, type_id: str, content: Json, *, team_id: str, by: str, copied_from: Json | None) -> None:
        at = now_iso()
        try:
            async with self._tx() as (c, team):
                if team_id != team:
                    raise RuntimeError("a type is created in the store's team")
                await c.execute(
                    self.head.insert().values(
                        id=type_id,
                        team_id=team_id,
                        origin=TEAM,
                        name=content["name"],
                        description=content.get("description", ""),
                        version=1,
                        published_version=None,
                        copied_from=copied_from,
                        created_at=at,
                        created_by=by,
                        updated_at=at,
                        updated_by=by,
                    )
                )
                await c.execute(
                    self.versions.insert().values(
                        team_id=team_id,
                        type_id=type_id,
                        version=1,
                        record=self.record_of(content),
                        saved_at=at,
                        saved_by=by,
                    )
                )
        except IntegrityError as e:
            raise Conflict(f"A {self.noun} {type_id} exists; choose another id.", code=self.taken_code) from e

    async def save_draft(self, type_id: str, content: Json, *, by: str) -> int:
        at = now_iso()
        async with self._tx() as (c, _team):
            # Locked so two saves or publishes at once take turns instead of both reading the same version.
            row = await self._row(c, type_id, lock=True)
            team = row.team_id
            n = row.version
            newest_published = row.published_version == n
            values = {"record": self.record_of(content), "saved_at": at, "saved_by": by}
            if newest_published:
                n += 1
                await c.execute(self.versions.insert().values(team_id=team, type_id=type_id, version=n, **values))
            else:
                await c.execute(
                    self.versions.update()
                    .where(
                        self.versions.c.team_id == team,
                        self.versions.c.type_id == type_id,
                        self.versions.c.version == n,
                    )
                    .values(**values)
                )
            await c.execute(
                self.head.update()
                .where(self.head.c.team_id == team, self.head.c.id == type_id)
                .values(
                    version=n,
                    name=content["name"],
                    description=content.get("description", ""),
                    updated_at=at,
                    updated_by=by,
                )
            )
        return n

    async def publish(self, type_id: str, version: int, *, by: str) -> None:
        at = now_iso()
        async with self._tx() as (c, _team):
            # Locked so two saves or publishes at once take turns instead of both reading the same version.
            row = await self._row(c, type_id, lock=True)
            if version != row.version or row.published_version == version:
                raise Conflict(
                    f"v{version} is not the newest draft of {type_id} (v{row.version}).", code="not_newest_draft"
                )
            team = row.team_id
            await c.execute(
                self.versions.update()
                .where(
                    self.versions.c.team_id == team,
                    self.versions.c.type_id == type_id,
                    self.versions.c.version == version,
                )
                .values(published_at=at, published_by=by)
            )
            await c.execute(
                self.head.update()
                .where(self.head.c.team_id == team, self.head.c.id == type_id)
                .values(published_version=version, updated_at=at, updated_by=by)
            )
