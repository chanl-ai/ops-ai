"""Typed records kept as versions (task types, c-288; case types, c-291), per tenant.

A type is seeded (shipped in a seed file, owned by no team: a system record every team reads and an admin may change,
and a team copies one to make its own) or a team's own, which only that team reads, edits or publishes (c-407). A save
edits the newest version while it is a draft, or opens the next one on top of a published version; a published version
never changes, so whatever pinned it (a task, a case) keeps reading what it was made with.
"""

from __future__ import annotations

from typing import Any, ClassVar, cast

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from ops_service_kit.errors import Conflict, NotFound
from ops_service_kit.ids import now_iso
from ops_store import Guarantee
from ops_store.team_scope import team_visible

from .tenancy import current_tenant, tenant_tx

SEED = "seed"
TEAM = "team"


def head_columns() -> list[sa.Column[Any]]:
    """A kind's type table: the type with its newest and newest published version."""
    return [
        sa.Column("tenant_id", sa.String(64), primary_key=True, default=current_tenant),
        sa.Column("id", sa.String(64), primary_key=True),
        # None for a seeded type, which no team edits.
        sa.Column("team_id", sa.String(64)),
        sa.Column("origin", sa.String(16), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text, nullable=False, default=""),
        # Newest saved version, draft or published, and the newest published one.
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("published_version", sa.Integer),
        # The type and version a copy started from.
        sa.Column("copied_from", sa.JSON),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("created_by", sa.String(320), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
        sa.Column("updated_by", sa.String(320), nullable=False),
    ]


def version_columns() -> list[sa.Column[Any]]:
    """A kind's version table: every saved version of a type."""
    return [
        sa.Column("tenant_id", sa.String(64), primary_key=True, default=current_tenant),
        sa.Column("type_id", sa.String(64), primary_key=True),
        sa.Column("version", sa.Integer, primary_key=True),
        # The record's content and its name and description as they were at this version.
        sa.Column("record", sa.JSON, nullable=False),
        sa.Column("saved_at", sa.String(32), nullable=False),
        sa.Column("saved_by", sa.String(320), nullable=False),
        sa.Column("published_at", sa.String(32)),
        sa.Column("published_by", sa.String(320)),
    ]


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

    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    def record_of(self, content: dict[str, Any]) -> dict[str, Any]:
        return {k: content[k] for k in self.record_keys if k in content}

    async def ensure_seeds(self, seeds: list[dict[str, Any]]) -> None:
        """Each seed at its file version, published and owned by no team; a seed whose file version is newer than the
        tenant's opens that version. Team types are never touched."""
        at = now_iso()
        async with tenant_tx(self.engine) as c:
            have = {
                str(r["id"]): r
                for r in (await c.execute(sa.select(self.head).where(self.head.c.origin == SEED))).mappings()
            }
            for s in seeds:
                v = int(s["version"])
                row = have.get(str(s["id"]))
                if row is not None and int(row["version"]) >= v:
                    continue
                version = {
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
                            team_id=None,
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
                        .where(self.head.c.id == s["id"])
                        .values(version=v, published_version=v, name=s["name"], updated_at=at, updated_by=SEED)
                    )
                await c.execute(self.versions.insert().values(**version, published_at=at, published_by=SEED))

    async def rows(self) -> list[dict[str, Any]]:
        async with tenant_tx(self.engine) as c:
            q = sa.select(self.head).where(team_visible(self.head)).order_by(self.head.c.origin, self.head.c.name)
            return [dict(r) for r in (await c.execute(q)).mappings()]

    async def _row(self, c: AsyncConnection, type_id: str, *, lock: bool = False) -> dict[str, Any]:
        q = sa.select(self.head).where(self.head.c.id == type_id, team_visible(self.head))
        r = (await c.execute(q.with_for_update() if lock else q)).mappings().first()
        if r is None:
            raise self.not_found(type_id)
        return dict(r)

    async def get(self, type_id: str) -> dict[str, Any]:
        """The type with its versions, newest first."""
        async with tenant_tx(self.engine) as c:
            row = await self._row(c, type_id)
            q = (
                sa.select(self.versions)
                .where(self.versions.c.type_id == type_id, team_visible(self.versions))
                .order_by(self.versions.c.version.desc())
            )
            row["versions"] = [dict(r) for r in (await c.execute(q)).mappings()]
        return row

    async def published(self, type_id: str, version: int | None = None) -> tuple[int, dict[str, Any]]:
        """(version, record) of a published version: the one named, or the newest when None."""
        async with tenant_tx(self.engine) as c:
            row = await self._row(c, type_id)
            n = version if version is not None else row["published_version"]
            if n is None:
                raise self.not_found(type_id)
            q = sa.select(self.versions).where(
                self.versions.c.type_id == type_id,
                self.versions.c.version == n,
                self.versions.c.published_at.is_not(None),
                team_visible(self.versions),
            )
            v = (await c.execute(q)).mappings().first()
        if v is None:
            raise self.not_found(type_id, n)
        return int(n), cast(dict[str, Any], v["record"])

    async def create(
        self, type_id: str, content: dict[str, Any], *, team_id: str, by: str, copied_from: dict[str, Any] | None
    ) -> None:
        at = now_iso()
        try:
            async with tenant_tx(self.engine) as c:
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
                        type_id=type_id, version=1, record=self.record_of(content), saved_at=at, saved_by=by
                    )
                )
        except IntegrityError as e:
            raise Conflict(f"A {self.noun} {type_id} exists; choose another id.", code=self.taken_code) from e

    async def save_draft(self, type_id: str, content: dict[str, Any], *, by: str) -> int:
        at = now_iso()
        async with tenant_tx(self.engine) as c:
            # Locked so two saves or publishes at once take turns instead of both reading the same version.
            row = await self._row(c, type_id, lock=True)
            n = int(row["version"])
            newest_published = row["published_version"] == n
            values = {"record": self.record_of(content), "saved_at": at, "saved_by": by}
            if newest_published:
                n += 1
                await c.execute(self.versions.insert().values(type_id=type_id, version=n, **values))
            else:
                await c.execute(
                    self.versions.update()
                    .where(self.versions.c.type_id == type_id, self.versions.c.version == n)
                    .values(**values)
                )
            await c.execute(
                self.head.update()
                .where(self.head.c.id == type_id)
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
        async with tenant_tx(self.engine) as c:
            # Locked so two saves or publishes at once take turns instead of both reading the same version.
            row = await self._row(c, type_id, lock=True)
            if version != row["version"] or row["published_version"] == version:
                raise Conflict(
                    f"v{version} is not the newest draft of {type_id} (v{row['version']}).", code="not_newest_draft"
                )
            await c.execute(
                self.versions.update()
                .where(self.versions.c.type_id == type_id, self.versions.c.version == version)
                .values(published_at=at, published_by=by)
            )
            await c.execute(
                self.head.update()
                .where(self.head.c.id == type_id)
                .values(published_version=version, updated_at=at, updated_by=by)
            )
