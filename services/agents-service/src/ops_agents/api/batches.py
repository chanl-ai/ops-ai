"""Starting a batch's rows (c-535): the workflow worker's tick reads every tenant's pending rows, a few at a time, and
starts each row's run inside its own tenant and team, with the row's run key so a race or a restart adopts the run
that key already names. A batch whose row met the model budget stops: there is no engine spend cap, and the rows after
it would meet the same refusal."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from itertools import groupby
from typing import Any

from ops_engine.store import DefinitionStore, RunStore
from ops_service_kit.logging import get_logger
from ops_store import background, isolation

from ..store.background import heartbeats
from ..store.batches import Batches, run_key
from ..store.engine import AsyncEngine, EngineTransactions
from .engine_runs import start_run

log = get_logger(__name__)
PER_TICK = 50
EVERY_S = 2.0
BATCH_VIA = "start:batch"


def _by_batch(rows: Iterable[dict[str, Any]]) -> Iterable[tuple[tuple[str, str, str], list[dict[str, Any]]]]:
    keyed = sorted(rows, key=lambda r: (r["tenant_id"], r["batch_id"], r["row"]))
    for key, group in groupby(keyed, key=lambda r: (r["tenant_id"], r["team_id"], r["batch_id"])):
        yield key, list(group)


async def start_pending(db: AsyncEngine, *, limit: int = PER_TICK) -> int:
    """One tick: starts up to `limit` pending rows and answers how many runs it started or adopted."""
    store = Batches(db)
    started = 0
    for (tenant, team, batch_id), rows in _by_batch(await store.pending(limit)):
        with isolation.scope(tenant, team):
            spent = await store.spent(batch_id)
            if spent is not None:
                await store.stop(batch_id, f"Stopped: the team's model budget ran out. {spent}")
                log.warning("batch_stopped", batch=batch_id, reason="budget")
                continue
            definitions = DefinitionStore(EngineTransactions(db))
            runs = RunStore(EngineTransactions(db))
            for row in rows:
                stored = await definitions.get(str(row["workflow_id"]), int(row["version"]), team=team)
                if stored is None:
                    await store.stop(batch_id, "Stopped: the workflow version this batch runs is gone.")
                    break
                run, _ = await start_run(
                    runs,
                    stored,
                    team_id=team,
                    mode=row["mode"],
                    input=dict(row["input"]),
                    run_key=run_key(batch_id, int(row["row"]), int(row["attempt"])),
                    created_by=str(row["created_by"]),
                    started_via=BATCH_VIA,
                )
                await store.started(batch_id, int(row["row"]), int(row["attempt"]), str(run["id"]))
                started += 1
    return started


async def start_forever(db: AsyncEngine, stop: asyncio.Event, *, every_s: float = EVERY_S) -> None:
    """The batch starter as a listed background process (Background page), in the workflow worker. Every worker
    runs it; a row two workers reach at once is started once, by its run key."""

    async def once() -> int:
        return await start_pending(db)

    await background.run("batch_starter", once, stop=stop, store=heartbeats(db), every_s=every_s)
