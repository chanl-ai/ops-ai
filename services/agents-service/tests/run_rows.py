"""A run written straight to the store, for tests that need a run row without a start: no input check, no API.
Product code cannot do this: only `ops_engine.starts` may import the writer (`.importlinter`)."""

from __future__ import annotations

from typing import Any, cast

from ops_engine.store import RunRow, Transactions
from ops_engine.store.new_runs import NewRun
from ops_engine.store.new_runs import write_run as write


async def write_run(tx: Transactions, run: dict[str, Any]) -> tuple[RunRow, bool]:
    return await write(tx, cast(NewRun, run))
