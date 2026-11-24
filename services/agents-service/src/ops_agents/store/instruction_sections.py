"""Each workspace's list of agent instruction sections, as an admin last saved it. No row means the workspace uses the
default list, which the service defines; resetting the list deletes the row."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, ClassVar

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from ops_store import Guarantee
from ops_store.dialect import db_now
from ops_store.schema import TENANT_SCOPED

from .base import metadata
from .tenancy import RuntimeStore, current_tenant

agent_instruction_sections = sa.Table(
    "agent_instruction_sections",
    metadata,
    sa.Column("tenant_id", sa.String(64), primary_key=True, default=current_tenant),
    sa.Column("document", sa.JSON, nullable=False),
    sa.Column("updated_by", sa.String(320), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    info=TENANT_SCOPED,
)


@dataclass(frozen=True)
class SavedSections:
    document: dict[str, Any]
    updated_by: str
    updated_at: datetime


def _mine() -> sa.ColumnElement[bool]:
    """The tenant filter in the query itself, for SQLite; on PostgreSQL and SQL Server the row policy applies it too."""
    return agent_instruction_sections.c.tenant_id == current_tenant()


class InstructionSections(RuntimeStore):
    # One row per tenant, replaced whole by a save that sends the full list: the last admin to save wins, and no write
    # depends on what was read before it.
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.TRANSACTION, Guarantee.CLOCK})

    async def get(self) -> SavedSections | None:
        """The workspace's saved list, or None when it uses the default."""
        t = agent_instruction_sections
        async with self.tx() as c:
            q = sa.select(t.c.document, t.c.updated_by, t.c.updated_at).where(_mine())
            row = (await c.execute(q)).first()
        if row is None:
            return None
        return SavedSections(document=dict(row.document), updated_by=str(row.updated_by), updated_at=row.updated_at)

    async def put(self, document: dict[str, Any], *, by: str) -> None:
        """Replaces the workspace's list with `document`."""
        # Update first, then insert under a savepoint: the dialect's upsert binds every value as a parameter on SQL
        # Server, so it cannot carry db_now(). A first save racing another first save loses the insert and updates.
        t = agent_instruction_sections
        values = {"document": document, "updated_by": by, "updated_at": db_now()}
        async with self.tx() as c:
            if (await c.execute(t.update().where(_mine()).values(**values))).rowcount:
                return
            try:
                async with self.attempt(c):
                    await c.execute(t.insert().values(tenant_id=current_tenant(), **values))
            except IntegrityError:
                await c.execute(t.update().where(_mine()).values(**values))

    async def delete(self) -> bool:
        """Resets the workspace to the default list; False when it already used it."""
        async with self.tx() as c:
            done = await c.execute(agent_instruction_sections.delete().where(_mine()))
            return done.rowcount > 0
