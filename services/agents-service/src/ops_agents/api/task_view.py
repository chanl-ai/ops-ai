"""A review step's task screen from its task type (c-288): the version the step pinned when it paused, bound to the
params it resolved then. Nothing here knows a type by id, so a team's copy draws as its seed does."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any, cast

from ops_engine.store import RunStore
from ops_store.team_scope import acting_team

from .. import task_types as tt
from ..store.cases import CaseStore
from ..store.engine import EngineTransactions
from ..store.task_assists import TaskAssistStore
from ..store.task_types import TaskTypeNotFound
from . import task_assist
from .deps import Runtime
from .review_text import describe_call, shown
from .task_type_seeds import task_type_store

_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?$")


def worded(value: Any) -> str:
    """A value as a reviewer reads it in a task: a date as 17 Jan 2027, anything else as the review wording does
    (review_text.shown: grouped numbers, yes or no, lists joined)."""
    if isinstance(value, str) and _DATE.match(value):
        try:
            when = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value
        return f"{when.day} {when:%b %Y}"
    return shown(value, money=False, currency=None)


class TaskReads:
    """What typed tasks read, once for a list of reviews rather than once per task: each task type version however
    many tasks use it, the listed steps' assists in one query, the listed runs' steps in one query the first time a task
    reads them (an old review's params, a type's cases), and their cases in one pass. A single review reads through one
    built for it alone."""

    def __init__(self, rt: Runtime, runs: list[dict[str, Any]], step_ids: list[str]) -> None:
        self.rt, self.runs, self.step_ids = rt, runs, step_ids
        self._types: dict[tuple[str | None, str, int | None], tuple[int, dict[str, Any]] | TaskTypeNotFound] = {}
        self._assists: dict[str, tuple[dict[str, Any], str]] | None = None
        self._cases: dict[str, list[dict[str, Any]]] | None = None
        self._steps: dict[str, list[dict[str, Any]]] = {}

    async def published(self, type_id: str, version: int | None, team: str | None = None) -> tuple[int, dict[str, Any]]:
        """A task type as the team of the run it serves reads it (`team`), or as the acting team."""
        key = (team, type_id, version)
        if key not in self._types:
            try:
                self._types[key] = await (await task_type_store(self.rt, team)).published(type_id, version)
            except TaskTypeNotFound as e:
                self._types[key] = e
        found = self._types[key]
        if isinstance(found, TaskTypeNotFound):
            raise found
        return found

    async def assist(self, step_id: str) -> tuple[dict[str, Any], str] | None:
        if self._assists is None:
            self._assists = await TaskAssistStore(self.rt.db).written_many(self.step_ids)
        return self._assists.get(step_id)

    def _listed(self, run: dict[str, Any]) -> list[dict[str, Any]]:
        return self.runs if any(str(r["id"]) == str(run["id"]) for r in self.runs) else [run]

    async def steps(self, run: dict[str, Any]) -> list[dict[str, Any]]:
        if str(run["id"]) not in self._steps:
            ids = [str(r["id"]) for r in self._listed(run)]
            self._steps |= await RunStore(EngineTransactions(self.rt.db)).steps_of(ids)
        return self._steps[str(run["id"])]

    async def cases(self, run: dict[str, Any]) -> list[dict[str, Any]]:
        if self._cases is None or str(run["id"]) not in self._cases:
            listed = self._listed(run)
            await self.steps(run)
            self._cases = (self._cases or {}) | await runs_cases(self.rt, listed, self._steps)
        return self._cases[str(run["id"])]


async def typed_task(
    rt: Runtime, payload: dict[str, Any], run: dict[str, Any] | None = None, reads: TaskReads | None = None
) -> dict[str, Any] | None:
    ref = cast(dict[str, Any] | None, payload.get("taskType"))
    if not ref:
        return None
    type_id, version = str(ref["id"]), cast(int | None, ref.get("version"))
    params = cast(dict[str, Any], payload.get("params") or {})
    step = str(payload.get("step_id") or "")
    reads = reads or TaskReads(rt, [run] if run is not None else [], [step])
    try:
        n, record = await reads.published(type_id, version, str(run["team_id"]) if run is not None else None)
    except TaskTypeNotFound as e:
        # Listed with the reason rather than dropped, as a review whose options cannot be read is.
        missing = {"field": "taskType", "severity": "error", "message": str(e)}
        return {
            "type": {"id": type_id, "version": version or 0, "name": type_id},
            "regions": [],
            "actions": [],
            "warnings": [missing],
        }
    if run is not None and "cases" in _declared(record) and "cases" not in params:
        # A type that shows cases gets the ones its run and child runs opened, not a value the step had to pass.
        params = {**params, "cases": await reads.cases(run)}
    bound = tt.bind(record, params, worded)
    # A write's preview in the operation's own words (c-508): its fields and sentence from the one describer, which the
    # Human Task page draws instead of naming the call's input keys itself.
    for region in cast(list[dict[str, Any]], bound["regions"]):
        call = cast(dict[str, Any], region.get("data") or {}).get("call")
        if region["region"] == "write_preview" and isinstance(call, dict) and cast(dict[str, Any], call).get("tool"):
            told = await describe_call(rt, cast(dict[str, Any], call), currency=None, money_key=None)
            region["data"] = region["data"] | {"fields": told["fields"], "sentence": told["sentence"]}
    # Task assist (c-302), when the team had it on as the step paused: after the question, before the evidence.
    if helped := task_assist.region(
        task_assist.settled(await reads.assist(step), datetime.now(UTC)),
        bound["actions"],
    ):
        bound["regions"].insert(1 if bound["regions"][:1] and bound["regions"][0]["region"] == "header" else 0, helped)
    return {
        "type": {"id": type_id, "version": n, "name": str(record.get("name") or type_id)},
        **bound,
        "warnings": tt.check_params(record, params),
    }


async def step_warnings(rt: Runtime, definition: dict[str, Any]) -> list[dict[str, Any]]:
    """What a saved workflow's typed review steps leave out (c-288): a task type that is not published, or a required
    param the step does not set. Warnings only: the owner's rule is that a missing setting never refuses a save, and
    the task shows the param's fallback line. A param set to a path is taken as set; its value is checked at the
    pause. Types are read in the acting team; a caller acting for every team (the dev header caller) holds no one
    team's types, so its saves are not checked."""
    out: list[dict[str, Any]] = []
    if acting_team() is None:
        return out
    for node in cast(list[dict[str, Any]], definition.get("nodes") or []):
        params = cast(dict[str, Any], node.get("parameters") or {})
        ref = params.get("taskType")
        if node.get("type") != "ops.flow.humanReview" or not isinstance(ref, dict):
            continue
        typed = cast(dict[str, Any], ref)
        try:
            _, record = await (await task_type_store(rt)).published(
                str(typed["id"]), cast(int | None, typed.get("version"))
            )
        except TaskTypeNotFound as e:
            out.append({"node": node["id"], "field": "taskType", "message": str(e)})
            continue
        given = params.get("params")
        if isinstance(given, str):
            continue
        for issue in tt.check_params(record, cast(dict[str, Any], given or {})):
            if issue["severity"] == "warning":
                out.append({"node": node["id"], "field": f"params.{issue['field']}", "message": issue["message"]})
    return out


def _declared(record: dict[str, Any]) -> dict[str, Any]:
    return cast(dict[str, Any], cast(dict[str, Any], record.get("params") or {}).get("properties") or {})


async def run_cases(rt: Runtime, run: dict[str, Any]) -> list[dict[str, Any]]:
    """The cases `run` and the runs its steps started opened, each with its subject, in the order they were opened."""
    return (await runs_cases(rt, [run]))[str(run["id"])]


async def runs_cases(
    rt: Runtime, runs: list[dict[str, Any]], steps: dict[str, list[dict[str, Any]]] | None = None
) -> dict[str, list[dict[str, Any]]]:
    """run_cases for each of `runs` in three queries however many there are: their steps (unless `steps` has them),
    the cases those runs and the runs they started are on, and the cases' subjects."""
    ids = [str(r["id"]) for r in runs]
    if steps is None or any(rid not in steps for rid in ids):
        steps = await RunStore(EngineTransactions(rt.db)).steps_of(ids)
    started = {
        rid: [
            str(cast(dict[str, Any], r)["runId"])
            for s in steps.get(rid, [])
            if isinstance(s.get("output"), dict)
            for r in cast(list[Any], cast(dict[str, Any], s["output"]).get("runs") or [])
            if isinstance(r, dict) and cast(dict[str, Any], r).get("runId")
        ]
        for rid in ids
    }
    store = CaseStore(rt.db)
    on = await store.cases_of_runs(list(dict.fromkeys([*ids, *(x for xs in started.values() for x in xs)])))
    subjects = await store.subjects(list(dict.fromkeys(on.values())))
    out: dict[str, list[dict[str, Any]]] = {}
    for rid in ids:
        mine = {rid, *started[rid]}
        opened = dict.fromkeys(case for ref, case in on.items() if ref in mine)
        out[rid] = [{"caseId": case, "subject": subjects[case]} for case in opened if case in subjects]
    return out
