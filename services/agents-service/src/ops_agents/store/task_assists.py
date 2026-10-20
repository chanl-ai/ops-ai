"""What task assist wrote for a typed task (c-302): one row per review step, written when the step paused, so the
assist is one model call per task however often the task is read."""

from __future__ import annotations

from typing import Any, ClassVar, cast

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_service_kit.ids import now_iso
from ops_store import Guarantee
from ops_store.schema import TENANT_SCOPED

from .base import metadata
from .tenancy import current_tenant, tenant_tx

task_assists = sa.Table(
    "task_assists",
    metadata,
    sa.Column("tenant_id", sa.String(64), primary_key=True, default=current_tenant),
    # The review step's id: run:node:iteration.
    sa.Column("step_id", sa.String(200), primary_key=True),
    sa.Column("assist", sa.JSON, nullable=False),
    sa.Column("created_at", sa.String(32), nullable=False),
    info=TENANT_SCOPED,
)


class TaskAssistStore:
    # The step id is a unique key: a second write for the same step is refused, so the first assist stays (CAS).
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.CAS})

    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    async def get(self, step_id: str) -> dict[str, Any] | None:
        async with tenant_tx(self.engine) as c:
            row = (await c.execute(sa.select(task_assists.c.assist).where(task_assists.c.step_id == step_id))).first()
        return cast(dict[str, Any], row[0]) if row else None

    async def written_many(self, step_ids: list[str]) -> dict[str, tuple[dict[str, Any], str]]:
        """written() for each step in one query, for a list of tasks; a step with no assist is left out."""
        if not step_ids:
            return {}
        t = task_assists
        async with tenant_tx(self.engine) as c:
            q = sa.select(t.c.step_id, t.c.assist, t.c.created_at).where(
                t.c.tenant_id == current_tenant(), t.c.step_id.in_(step_ids)
            )
            rows = (await c.execute(q)).all()
        return {str(r[0]): (cast(dict[str, Any], r[1]), str(r[2])) for r in rows}

    async def written(self, step_id: str) -> tuple[dict[str, Any], str] | None:
        """The step's assist and when it was recorded, which tells a pending one that can no longer be filled."""
        async with tenant_tx(self.engine) as c:
            q = sa.select(task_assists.c.assist, task_assists.c.created_at).where(task_assists.c.step_id == step_id)
            row = (await c.execute(q)).first()
        return (cast(dict[str, Any], row[0]), str(row[1])) if row else None

    async def put(self, step_id: str, assist: dict[str, Any]) -> bool:
        """Keeps the first assist a step was given: a replayed pause writes nothing new. False when one was there."""
        try:
            async with tenant_tx(self.engine) as c:
                await c.execute(task_assists.insert().values(step_id=step_id, assist=assist, created_at=now_iso()))
        except IntegrityError:
            return False
        return True

    async def fill(self, step_id: str, assist: dict[str, Any]) -> None:
        """Replaces the pending marker `put` recorded with what the model wrote, or with the failure."""
        async with tenant_tx(self.engine) as c:
            await c.execute(task_assists.update().where(task_assists.c.step_id == step_id).values(assist=assist))
