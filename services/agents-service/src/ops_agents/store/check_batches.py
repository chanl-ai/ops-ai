"""A check's batch written with its place: the batch, its rows and the binding's cursor commit in one transaction.

A Files changed trigger reads a watch's events after its cursor and writes one batch for what it read. The cursor
moves by compare-and-set (`poll_cursors.move`), so of two collectors of one check only the first writes; the rows'
unique key (`ux_run_batch_rows_item`) keeps one row per file version per workflow, so a check that overlaps an
earlier one leaves out the versions that one wrote. Rows already written are selected first and left out; a race
that still meets the index is retried once after reading again."""

from __future__ import annotations

from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from ops_service_kit.http import Json
from ops_service_kit.ids import new_id, now_iso

from .batches import BatchOut, run_batch_rows, run_batches
from .poll_cursors import PollCursor, move
from .tenancy import current_tenant, tenant_tx


@dataclass(frozen=True)
class CheckBatch:
    team_id: str
    workflow_id: str
    version: int
    mode: str
    watch_id: str
    # The batch page's title: the watch and the check's time.
    label: str
    checked_at: str
    created_by: str


@dataclass(frozen=True)
class CheckRow:
    item_key: str
    input: Json
    # pending (a new or changed file, started by the batch starter), removed or failed (never started).
    status: str
    failure_code: str | None = None
    reason: str | None = None


class _Lost(Exception):
    """Another collector moved the place first; this one's transaction is rolled back."""


async def _write(c: AsyncConnection, binding_id: str, *, watch_id: str, expected: str | None, to: str,
                 batch: CheckBatch, rows: list[CheckRow]) -> BatchOut | None:  # fmt: skip
    if not await move(c, binding_id, expected=expected, to=PollCursor(watch_id, "", to)):
        raise _Lost
    r = run_batch_rows
    keys = [x.item_key for x in rows]
    held = set(
        (
            await c.execute(
                sa.select(r.c.item_key).where(
                    r.c.tenant_id == current_tenant(), r.c.workflow_id == batch.workflow_id, r.c.item_key.in_(keys)
                )
            )
        ).scalars()
    ) if keys else set[str]()  # fmt: skip
    new = [x for x in rows if x.item_key not in held]
    if not new:
        return None
    batch_id = new_id("batch")
    out = {
        "id": batch_id,
        # A check with no Group by is one batch, its own group.
        "group_key": batch_id,
        "team_id": batch.team_id,
        "workflow_id": batch.workflow_id,
        "version": batch.version,
        "mode": batch.mode,
        "origin": "check",
        "file_id": None,
        "file_name": batch.label[:300],
        "watch_id": batch.watch_id,
        "checked_at": batch.checked_at,
        "total": len(new),
        "created_by": batch.created_by,
        "created_at": now_iso(),
    }
    await c.execute(run_batches.insert().values(**out))
    await c.execute(
        r.insert(),
        [
            {
                "batch_id": out["id"],
                "row": i,
                "team_id": batch.team_id,
                "workflow_id": batch.workflow_id,
                "item_key": x.item_key,
                "input": x.input,
                "status": x.status,
                "failure_code": x.failure_code,
                "reason": (x.reason or None) and x.reason[:500],
            }
            for i, x in enumerate(new, 1)
        ],
    )
    return BatchOut.model_validate(out)


async def write_check(
    engine: AsyncEngine,
    *,
    binding_id: str,
    watch_id: str,
    expected: str | None,
    to: str,
    batch: CheckBatch,
    rows: list[CheckRow],
) -> BatchOut | None:
    """Moves the binding's cursor from `expected` to `to` and writes the batch of `rows` not already written, in one
    transaction. None when the place had moved (nothing is written) or every row was written before (only the
    cursor moves)."""
    for attempt in range(2):
        try:
            async with tenant_tx(engine) as c:
                return await _write(c, binding_id, watch_id=watch_id, expected=expected, to=to, batch=batch, rows=rows)
        except _Lost:
            return None
        except IntegrityError:
            if attempt:
                raise
    return None


__all__ = ["CheckBatch", "CheckRow", "write_check"]
