"""The background processes (c-516). GET /health/background: agents-service's processes and their state, with no
record's data, for `make health` and the staging check. GET /v1/background: every listed process of every service and
the latest jobs, for an account admin's Govern > Background page; anyone else gets not found.

The page's one call reads agents-service's own heartbeats and jobs, and only reads files', documents' and tools'
/health/background for theirs; it never acts on another service. A service that does not answer shows its processes
as not reported."""

from __future__ import annotations

import asyncio
import time
from typing import Annotated, Any, TypeAlias, cast

import httpx
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from ops_access import ANY_TEAM, can
from ops_service_kit.background import BackgroundHealthOut, BackgroundProcessOut
from ops_service_kit.errors import Forbidden, NotFound
from ops_service_kit.http import Envelope, Out
from ops_service_kit.settings import Settings
from ops_store import background

from ...store.background import BackgroundJobs, heartbeats
from ...store.tenancy import current_tenant
from ..auth import Principal, caller, caller_of
from ..deps import Runtime, runtime
from ..envelope import ok

Rt: TypeAlias = Annotated[Runtime, Depends(runtime)]  # noqa: UP040 - FastAPI reads Annotated aliases
Me: TypeAlias = Annotated[Principal, Depends(caller)]  # noqa: UP040

router = APIRouter()

# How long the page waits for another service's /health/background before showing its processes as not reported.
READ_TIMEOUT_S = 2.0
LATEST_JOBS = 50


class BackgroundJobOut(Out):
    id: str
    process: str
    process_title: str
    summary: str
    outcome: str
    team_id: str
    team_name: str | None
    at: str


class BackgroundOut(Out):
    processes: list[BackgroundProcessOut]
    jobs: list[BackgroundJobOut]
    # Services whose /health/background did not answer; their processes read not_reported.
    unreachable: list[str]


@router.get("/health/background", response_model=BackgroundHealthOut)
async def health_background(rt: Rt) -> dict[str, Any]:
    beats = await heartbeats(rt.db).read()
    return {"processes": background.report(beats, "agents", time.time())}


def _require_account_admin(me: Principal) -> None:
    """An account admin holds Admin in every team (the `*` assignment), the check Settings > Workspace uses. Anyone
    else is told the page does not exist, as for a record of another team."""
    try:
        can(caller_of(me), "access", "manage", team=ANY_TEAM, what="background processes", from_any_team=True)
    except Forbidden as e:
        raise NotFound("Background processes") from e


def _urls(settings: Settings) -> dict[str, str | None]:
    return {
        "files": settings.files_url,
        "documents": settings.documents_url,
        "tools": settings.tools_url or settings.gateway_url,
    }


async def _read(client: httpx.AsyncClient, service: str, url: str | None) -> tuple[str, list[dict[str, Any]] | None]:
    if not url:
        return service, None
    try:
        answer = await client.get(f"{url.rstrip('/')}/health/background", timeout=READ_TIMEOUT_S)
        answer.raise_for_status()
        return service, cast(list[dict[str, Any]], answer.json()["processes"])
    except (httpx.HTTPError, KeyError, ValueError):
        return service, None


def _not_reported(service: str) -> list[dict[str, Any]]:
    return [
        {
            "key": p.key,
            "service": p.service,
            "title": p.title,
            "does": p.does,
            "everySeconds": p.every_s,
            "state": "not_reported",
            "instances": 0,
            "lastRunAt": None,
            "nextRunAt": None,
            "doneHour": 0,
            "waiting": None,
            "lastError": None,
            "lastErrorAt": None,
        }
        for p in background.PROCESSES
        if p.service == service
    ]


@router.get("/v1/background", response_model=Envelope[BackgroundOut])
async def background_processes(rt: Rt, me: Me) -> JSONResponse:
    _require_account_admin(me)
    now = time.time()
    processes = background.report(await heartbeats(rt.db).read(), "agents", now, detail=True)
    unreachable: list[str] = []
    async with httpx.AsyncClient() as client:
        answers = await asyncio.gather(*(_read(client, s, u) for s, u in _urls(Settings()).items()))
    for service, found in answers:
        if found is None:
            unreachable.append(service)
        processes += found if found is not None else _not_reported(service)
    order = {p.key: i for i, p in enumerate(background.PROCESSES)}
    processes.sort(key=lambda p: order.get(str(p["key"]), len(order)))
    jobs = await BackgroundJobs(rt.db).latest_everywhere(current_tenant(), limit=LATEST_JOBS)
    names = rt.team_names
    team_names = {t: (await names.name(t) if names is not None else None) for t in {j.team_id for j in jobs}}
    return ok(
        {
            "processes": processes,
            "jobs": [j.as_wire(team_names.get(j.team_id)) for j in jobs],
            "unreachable": unreachable,
        }
    )
