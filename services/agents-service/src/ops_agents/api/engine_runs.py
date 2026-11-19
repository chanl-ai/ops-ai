"""The one way a v2 workflow run starts. A person's or an API key's call (`POST /v1/runs`), an agent calling the
workflow as a tool, a trigger (Email received) and a Start workflow step (`WorkflowStarts`) all come here, so the
live-version rule, the run key's dedupe and the trigger's input schema hold for every caller. The run is written by
the engine's entry (`ops_engine.starts.start`), which checks the input; this module words its refusals for the API.
Who may start is the caller's check, made before this."""

from __future__ import annotations

import hashlib
from typing import Any, Literal

from ops_engine import default_registry, starts
from ops_engine.ports import RunRefusedError, StartedRun
from ops_engine.starts import InputRefusedError
from ops_engine.store import (
    CHILD_PREFIX,
    RUN_PREFIX,
    DefinitionGoneError,
    DefinitionRow,
    DefinitionStore,
    NotLiveError,
    RunRow,
    RunStore,
)
from ops_service_kit.errors import ApiError, Conflict, NotFound, Unprocessable
from ops_service_kit.http import Json
from ops_service_kit.ids import new_id

REGISTRY = default_registry()


def refused(e: InputRefusedError) -> Unprocessable:
    """An input its schema refuses as the API answers it: 422 with `details.path` the schema property, `reason` what
    is wrong with it, and `missing` the labels of required fields left empty."""
    details: Json = {"path": e.field, "reason": e.reason}
    if e.missing:
        details["missing"] = list(e.missing)
    return Unprocessable(str(e), code=e.code, details=details)


def checked_values(schema: Json, values: Json) -> Json:
    """A start form's values as a run takes them (`ops_engine.starts.typed_values`), or 422."""
    try:
        return starts.typed_values(schema, values)
    except InputRefusedError as e:
        raise refused(e) from e


def checked_input(stored: DefinitionRow, values: Json) -> Json:
    """`values` as a run on `stored` takes them, or 422. `start_run` holds every run to this; a caller that must
    refuse before it writes anything else (a batch before it stores its rows) asks first."""
    try:
        return starts.run_input(stored.definition, values, REGISTRY)
    except InputRefusedError as e:
        raise refused(e) from e


async def live_version(
    store: DefinitionStore, workflow_id: str, version: int | None, *, team: str | None
) -> DefinitionRow:
    """The version a live run of `workflow_id` starts on; 409 `workflow_paused` while it is paused, `not_live` when it
    has no live version or `version` names another."""
    current = await store.serving(workflow_id, team=team)
    if current is not None and current.archived_at:
        raise Conflict(f"{workflow_id} is archived; restore it to start runs.", code="workflow_archived")
    if current is not None and current.stage == "paused":
        raise Conflict(f"{workflow_id} is paused; resume it to start live runs.", code="workflow_paused")
    if current is None or (version is not None and version != current.version):
        which = f"v{version} of {workflow_id} is not live" if current else f"{workflow_id} has no live version"
        raise Conflict(f"{which}; publish it through Reviews or start a test run.", code="not_live")
    return current


async def start_run(
    runs: RunStore,
    stored: DefinitionRow,
    *,
    team_id: str,
    mode: Literal["live", "test"],
    input: dict[str, Any],
    run_key: str | None,
    created_by: str,
    started_via: str | None = None,
    started_by_approver: bool = False,
    after_seconds: float = 0,
) -> tuple[RunRow, bool]:
    """Writes the run on `stored` (a definition row) with its start work row, or returns the run that already has
    `run_key`. Returns (run, created). An input the trigger's schema refuses answers 422 `invalid_input` naming the
    field and the reason, and text that reads as a declared number is stored as the number. A version paused or
    superseded since it was read is refused here, under the lock `RunStore.create` takes. `started_by_approver` is
    `approves_own_writes` of the person starting it, read here because the worker that runs its steps has no
    principal."""
    run_id = new_id(RUN_PREFIX.rstrip("_"))
    try:
        return await starts.start(
            runs,
            stored,
            {
                "id": run_id,
                "team_id": team_id,
                "workflow_id": stored.workflow_id,
                "version": stored.version,
                "digest": stored.digest,
                "run_key": run_key or run_id,
                "mode": mode,
                "input": input,
                "created_by": created_by,
                "started_via": started_via,
                "started_by_approver": started_by_approver,
                "after_seconds": after_seconds,
            },
            REGISTRY,
        )
    except InputRefusedError as e:
        raise refused(e) from e
    except DefinitionGoneError as e:
        raise NotFound(f"Workflow definition {stored.workflow_id} was not found: {str(e).rstrip('.')}.") from e
    except NotLiveError as e:
        code = {"paused": "workflow_paused", "archived": "workflow_archived"}.get(e.stage, "not_live")
        raise Conflict(f"v{stored.version} of {stored.workflow_id}: {e}.", code=code) from e


# Runs started by runs, counted up from the first: a workflow that starts itself, directly or through another, stops
# here instead of starting runs without end.
MAX_CHILD_DEPTH = 5


async def runs_above(runs: RunStore, run: RunRow) -> list[RunRow]:
    """The runs that started `run`, nearest first (starters_of)."""
    return await starters_of(runs, run.created_by, run.team_id)


async def starters_of(runs: RunStore, created_by: str, team_id: str | None) -> list[RunRow]:
    """The runs that started a run created by `created_by` in `team_id`, nearest first, walking `created_by` up to
    MAX_CHILD_DEPTH. The walk stops at a parent that is gone or belongs to another team: for this run that parent does
    not exist (identity-and-tenancy.md, "The team is the workspace"). The one walk of a run's starters; every reader
    that climbs the chain uses it, a reader holding only the run's mapping included."""
    above: list[RunRow] = []
    by = created_by
    while len(above) < MAX_CHILD_DEPTH and by.startswith(CHILD_PREFIX):
        parent = await runs.row(by[len(CHILD_PREFIX) :])
        if parent is None or parent.team_id != team_id:
            break
        above.append(parent)
        by = parent.created_by
    return above


async def first_run(runs: RunStore, run: RunRow) -> RunRow:
    """The run whose trigger began `run`'s work: the top of `runs_above`, or `run` itself."""
    return (await runs_above(runs, run) or [run])[-1]


def child_run_key(key: str) -> str:
    """The child's run key from the step's key (parent run, step, iteration, item); hashed when it would not fit the
    column."""
    plain = f"child:{key}"
    return plain if len(plain) <= 200 else "child:" + hashlib.sha256(key.encode()).hexdigest()[:40]


class WorkflowStarts:
    """The engine's RunPort: a Start workflow step's child runs. A child runs in its parent's team and mode, so a test
    run never starts live work and a run never starts another team's workflow; a live child needs the workflow's live
    version. It runs inside the worker's pass, under the parent run's tenant."""

    def __init__(self, runs: RunStore, definitions: DefinitionStore) -> None:
        self.runs, self.definitions = runs, definitions

    async def start(self, parent_run_id: str, workflow: str, input: Json, key: str) -> StartedRun:
        run_key = child_run_key(key)
        # A retried or re-run step finds its child even if the workflow has been paused since.
        if (found := await self.runs.by_key(workflow, run_key)) is not None:
            return StartedRun(found.id, False)
        parent = await self.runs.row(parent_run_id)
        if parent is None:
            raise RunRefusedError(f"run {parent_run_id} is gone", "parent_gone")
        if await self.depth(parent) >= MAX_CHILD_DEPTH:
            message = f"runs started by runs are {MAX_CHILD_DEPTH} deep here; {workflow} is not started again"
            raise RunRefusedError(message, "too_deep")
        team = parent.team_id
        if not team:
            # No team would read every team's workflows (DefinitionStore sees all rows for team None).
            raise RunRefusedError(f"run {parent_run_id} has no team, so it starts no workflows", "no_team")
        stored = await self.definitions.row(workflow, team=team)
        if stored is None:
            raise RunRefusedError(f"this team has no workflow {workflow}", "not_found")
        mode = "test" if parent.mode == "test" else "live"
        try:
            if mode == "live":
                stored = await live_version(self.definitions, workflow, None, team=team)
            run, created = await start_run(
                self.runs,
                stored,
                team_id=team,
                mode=mode,
                input=input,
                run_key=run_key,
                created_by=f"{CHILD_PREFIX}{parent_run_id}",
            )
        except ApiError as e:
            raise RunRefusedError(str(e), e.code or "refused") from e
        return StartedRun(run.id, created)

    async def children(self, parent_run_id: str, key_prefix: str, *, outputs: bool = False) -> list[Json]:
        """The children a step started, read on the parent index; their run keys carry the `child:` prefix
        child_run_key gives them. A key hashed for being over 194 characters would not match; run id, step id and
        iteration stay far under that."""
        return await self.runs.children(parent_run_id, f"child:{key_prefix}", outputs=outputs)

    async def depth(self, run: RunRow) -> int:
        """How many runs started this one, up to the limit."""
        return len(await runs_above(self.runs, run))
