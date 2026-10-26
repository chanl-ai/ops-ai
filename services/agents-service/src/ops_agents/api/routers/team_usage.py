"""What still runs in a team, for platform-service before it deletes the team or closes its workspace (c-529): a
service holding `workflows:view`, or a person with workflows.view in their team.

Runs in progress are the team's runs of both engines that have not finished (a run waiting for a person counts);
live workflows are the team's workflows whose status is live, by name, so the console can say which ones block a
delete. Only the team the token names is read (c-507): a service naming no team reads nothing, and a team in the
query is never read.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, TypeAlias

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from ops_access import can
from ops_engine.store import TERMINAL, RunStore
from ops_identity import CurrentTenantCaller
from ops_service_kit.http import Envelope, Out

from ...store.engine import EngineTransactions
from ...store.graphs import GraphStore
from ..deps import Runtime, runtime
from ..envelope import ok
from ..workflow_registry import registry
from . import engine

router = APIRouter(prefix="/v1/teams/usage")
Rt: TypeAlias = Annotated[Runtime, Depends(runtime)]  # noqa: UP040 - FastAPI reads Annotated aliases

# The first engine's thread statuses that mean it ended; any other is still running or waiting.
V1_ENDED = frozenset({"done", "error", "lease_lost"})


class TeamUsage(Out):
    runs_in_progress: int
    live_workflows: list[str]


@router.get("", response_model=Envelope[TeamUsage])
async def team_usage(rt: Rt, caller: CurrentTenantCaller) -> JSONResponse:
    team = None if caller.kind == "service" else caller.team_id
    can(caller, "workflows", "view", team=team, what="what runs in a team")
    team_id = caller.team_id
    if not team_id:
        return ok({"runsInProgress": 0, "liveWorkflows": []})
    v1 = [r for r in await registry(rt).rows() if r["team_id"] == team_id]
    mine = {str(r["id"]) for r in v1}
    v1_running = sum(
        1 for g, status, _ in await GraphStore(rt.db).thread_stats() if g in mine and status not in V1_ENDED
    )
    _, _, by_status = await RunStore(EngineTransactions(rt.db)).page(team_id=team_id, limit=1)
    v2_running = sum(n for status, n in by_status.items() if status not in TERMINAL)
    since = (datetime.now(UTC) - timedelta(days=1)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    v2 = [w for w in await engine.v2_workflow_rows(rt, since) if w["teamId"] == team_id]
    live = sorted(
        {str(r["name"]) for r in v1 if r["status"] == "live"} | {str(w["name"]) for w in v2 if w["status"] == "live"}
    )
    return ok({"runsInProgress": v1_running + v2_running, "liveWorkflows": live})
