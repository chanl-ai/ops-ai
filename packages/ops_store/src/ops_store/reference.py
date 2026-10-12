"""A reference audit log on SQLAlchemy Core, for a service that has none yet to start from (and the audit suite's
own check): the change and its entry are written in one transaction, and the entry column refuses null."""

from __future__ import annotations

from typing import Any, ClassVar

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from .guarantees import Guarantee

metadata = sa.MetaData()
audited = sa.Table(
    "store_ref_audited",
    metadata,
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("value", sa.Text, nullable=False),
)
audit_entries = sa.Table(
    "store_ref_audit_entries",
    metadata,
    sa.Column("seq", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("entity_id", sa.String(64), nullable=False, index=True),
    sa.Column("entry", sa.JSON(none_as_null=True), nullable=False),
)


class SqlAuditLog:
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.TRANSACTION})

    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    async def create(self) -> SqlAuditLog:
        async with self.engine.begin() as c:
            await c.run_sync(metadata.create_all)
        return self

    async def apply(self, entity_id: str, value: str, entry: dict[str, Any] | None) -> None:
        async with self.engine.begin() as c:
            updated = await c.execute(audited.update().where(audited.c.id == entity_id).values(value=value))
            if updated.rowcount == 0:
                await c.execute(audited.insert().values(id=entity_id, value=value))
            await c.execute(audit_entries.insert().values(entity_id=entity_id, entry=entry))

    async def value(self, entity_id: str) -> str | None:
        async with self.engine.connect() as c:
            return (await c.execute(sa.select(audited.c.value).where(audited.c.id == entity_id))).scalar()

    async def entries(self, entity_id: str) -> int:
        q = sa.select(sa.func.count()).select_from(audit_entries).where(audit_entries.c.entity_id == entity_id)
        async with self.engine.connect() as c:
            return int((await c.execute(q)).scalar_one())
