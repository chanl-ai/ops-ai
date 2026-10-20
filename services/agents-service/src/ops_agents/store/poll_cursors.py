"""Where each polled source stands (c-187): one row per binding, today the Email received trigger of one workflow.
The cursor moves only after a poll handled every item up to it, so a poll that dies starts again from the row.

The row also keeps the mailbox and folder the cursor belongs to: a new live version that watches another folder must
not continue from a cursor of the old one."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_service_kit.ids import now_iso
from ops_store import Guarantee
from ops_store.schema import TENANT_SCOPED

from .base import metadata
from .tenancy import current_tenant, tenant_tx

poll_cursors = sa.Table(
    "poll_cursors",
    metadata,
    sa.Column("tenant_id", sa.String(64), primary_key=True, default=current_tenant),
    # email:<workflow id>
    sa.Column("binding_id", sa.String(80), primary_key=True),
    sa.Column("source", sa.String(320), nullable=False),
    sa.Column("folder", sa.String(200), nullable=False),
    sa.Column("cursor", sa.Text(), nullable=False),
    sa.Column("updated_at", sa.String(32), nullable=False),
    info=TENANT_SCOPED,
)


@dataclass(frozen=True)
class PollCursor:
    source: str
    folder: str
    cursor: str


class PollCursors:
    # One poller per binding at a time (the caller holds the binding's lease), so a save replaces the row.
    requires: ClassVar[frozenset[Guarantee]] = frozenset()

    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    async def get(self, binding_id: str) -> PollCursor | None:
        t = poll_cursors
        q = sa.select(t.c.source, t.c.folder, t.c.cursor).where(
            t.c.tenant_id == current_tenant(), t.c.binding_id == binding_id
        )
        async with tenant_tx(self.engine) as c:
            row = (await c.execute(q)).first()
        return PollCursor(row.source, row.folder, row.cursor) if row else None

    async def read_at(self, binding_ids: list[str]) -> dict[str, str]:
        """When each binding's mailbox was last read (its cursor saved), by binding id; a binding never read is left
        out."""
        if not binding_ids:
            return {}
        t = poll_cursors
        q = sa.select(t.c.binding_id, t.c.updated_at).where(
            t.c.tenant_id == current_tenant(), t.c.binding_id.in_(binding_ids)
        )
        async with tenant_tx(self.engine) as c:
            return {r.binding_id: r.updated_at for r in await c.execute(q)}

    async def save(self, binding_id: str, at: PollCursor) -> None:
        t = poll_cursors
        values = {"source": at.source, "folder": at.folder, "cursor": at.cursor, "updated_at": now_iso()}
        try:
            async with tenant_tx(self.engine) as c:
                await c.execute(t.insert().values(binding_id=binding_id, **values))
        except IntegrityError:
            async with tenant_tx(self.engine) as c:
                await c.execute(
                    t.update().where(t.c.tenant_id == current_tenant(), t.c.binding_id == binding_id).values(**values)
                )
