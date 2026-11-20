"""The one write of a new run. Only `ops_engine.starts` imports this module, which the import contract
`runs-written-by-the-start-entry` in `.importlinter` holds: a run is written by `ops_engine.starts.start`, after its
input is held to the schema its trigger declares, and by nothing else. The package does not export `write_run`."""

from __future__ import annotations

from typing import Any, NotRequired, TypedDict, cast

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from ops_service_kit.http import Json
from ops_store.dialect import locked

from .clock import db_now, now_iso
from .runs import DefinitionGoneError, NotLiveError, RunRow, RunStore
from .tables import ENGINE_BUILD, engine_definitions, engine_runs, engine_work
from .tx import Transactions


class NewRun(TypedDict):
    """A run to write: the columns of `engine_runs` its starter sets, and how long its start work row waits."""

    id: str
    team_id: str
    workflow_id: str
    version: int
    digest: str
    run_key: str
    mode: str
    input: Json
    created_by: str
    started_via: NotRequired[str | None]
    started_by_approver: NotRequired[bool]
    after_seconds: NotRequired[float]


async def write_run(tx: Transactions, new: NewRun) -> tuple[RunRow, bool]:
    """Writes the run (status queued) and its start work row; a run with the same key is returned instead.
    A live run is refused (NotLiveError) unless the version it pins is live, read under the same lock a pause
    takes, so a pause and a start cannot both pass. Returns (run, created)."""
    at = now_iso()
    delay = float(new.get("after_seconds") or 0)
    run = {k: v for k, v in new.items() if k != "after_seconds"}
    values = {**run, "tenant_id": tx.tenant(), "status": "queued", "created_at": at, "updated_at": at}
    d = engine_definitions
    try:
        async with tx.tenant_tx() as c:
            # The pinned version, locked until the run commits: a delete of the workflow waits for this start
            # (and then sees its run), or ran first and the start finds the version gone.
            version = sa.select(d.c.stage, d.c.archived_at).where(
                d.c.tenant_id == values["tenant_id"],
                d.c.workflow_id == run["workflow_id"],
                d.c.version == run["version"],
                d.c.digest == run["digest"],
            )
            # `locked` is typed for a one-entity select; this one reads two columns.
            pinned = await c.execute(locked(cast("sa.Select[Any]", version), d))
            found = pinned.first()
            if found is None:
                raise DefinitionGoneError(f"{run['workflow_id']} version {run['version']} no longer exists")
            if found.archived_at is not None:
                raise NotLiveError("archived")
            if run["mode"] == "live" and found.stage != "live":
                raise NotLiveError(str(found.stage))
            await c.execute(engine_runs.insert().values(**values))
            await c.execute(
                engine_work.insert().values(
                    tenant_id=values["tenant_id"],
                    run_id=run["id"],
                    kind="start",
                    payload=None,
                    dedupe_key=f"start:{run['id']}",
                    status="queued",
                    build=ENGINE_BUILD,
                    available_at=db_now(c) + delay,
                    attempts=0,
                    created_at=at,
                )
            )
    except IntegrityError:
        found = await RunStore(tx).by_key(str(run["workflow_id"]), str(run["run_key"]))
        if found is None:
            raise
        return found, False
    return await RunStore(tx).row(str(run["id"])) or RunRow.model_validate(values), True
