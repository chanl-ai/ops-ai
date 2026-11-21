"""A kept eval run of an agent's saved cases: the one way such a run starts and is stored, which the Run button, a
publish check and the CLI each call (`run_saved`). Scoring is `app.evals`; who may run is the caller's check."""

from __future__ import annotations

import time
from typing import cast

from ops_agents.app.evals import TurnFn, parse_cases, run_eval, stored_run
from ops_agents.domain.evals import ASSET_AGENT, CASE_ACTIVE, CHECK_STATUS_PASS
from ops_service_kit.http import Json, JsonList
from ops_service_kit.ids import now_iso

from ..store.agent_registry import AgentRow
from ..store.evals import EvalStore
from .agent_test import one_test_turn
from .auth import Principal, started_by
from .deps import Runtime


def version_turn(rt: Runtime, row: AgentRow, version: int) -> TurnFn:
    """One test turn of the agent at `version`, through the single-turn harness (`one_test_turn`)."""

    async def turn(message: str, collections: tuple[str, ...]) -> Json:
        at = row.model_copy(update={"version": version})
        return await one_test_turn(rt, row.id, message, row=at, collections=collections or None)

    return turn


async def run_saved(rt: Runtime, me: Principal, row: AgentRow, *, trigger: str) -> Json:
    """Runs the agent's active saved cases on its newest version, and on the live one when that is another, and keeps
    the run, so repeating it keeps a second run. Answers the run as stored (`stored_run`). No saved cases, or an
    unknown check type, is 422. The caller checks who may run (`evals.run`)."""
    store = EvalStore(rt.db)
    cases = parse_cases([x["body"] for x in await store.cases(ASSET_AGENT, row.id) if x["status"] == CASE_ACTIVE])
    version, published = int(row.version), row.published_version
    live = int(published) if published is not None and int(published) != version else None
    started = time.perf_counter()
    run = await run_eval(
        row.id, cases, version_turn(rt, row, version), version_turn(rt, row, live) if live is not None else None
    )
    # The run's own JSON (run_eval), read as it was written there.
    results, summary = cast(JsonList, run["results"]), cast(Json, run["summary"])
    live_passed = (
        sum(cast(Json, cast(Json, r)["live"])["status"] == CHECK_STATUS_PASS for r in results)
        if live is not None
        else None
    )
    stored: Json = {
        "id": run["id"],
        "team_id": row.team_id,
        "kind": ASSET_AGENT,
        "asset_id": row.id,
        "version": version,
        "live_version": live,
        "trigger": trigger,
        "passed": summary["passed"],
        "total": summary["total"],
        "live_passed": live_passed,
        "regressions": summary["regressions"],
        "duration_ms": round((time.perf_counter() - started) * 1000),
        "cost_usd": 0.0,
        "results": results,
        "started_by": started_by(me),
        "ran_at": now_iso(),
    }
    await store.add_run(stored)
    return stored_run(stored)
