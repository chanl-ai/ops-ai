"""/v1/assurance: the Evals page's suites, runs and publish checks; the saved cases on an agent or a skill; and an
agent's kept runs, which its Evals tab reads.

The saved-case and agent-run routes answer in one request transaction (`Tx`), so a change and the cases read back are
one moment. The three assurance lists take none: each pages in SQL in its own transaction (`api/assurance.py`), then
names the page's teams through platform-service (`team_name`) with no connection held.
"""

from __future__ import annotations

from typing import Annotated, Any, TypeAlias

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import Field

from ops_access import can
from ops_agents.app.evals import parse_cases, stored_run
from ops_agents.domain.evals import ASSET_AGENT, ASSET_SKILL, CASE_ACTIVE
from ops_identity.fastapi import Tx
from ops_service_kit.errors import NotFound
from ops_service_kit.http import Envelope, In, ListResult, Out
from ops_service_kit.listing import ListParams, ListQuery

from ...store.evals import EvalStore
from ...store.skills import SkillRegistry
from .. import assurance
from ..agent_registry import registry as agent_registry
from ..assurance_schemas import GateList, RunList, SuiteList
from ..auth import Principal, caller_of, principal, reader_of
from ..deps import Runtime, runtime
from ..envelope import ok
from ..schemas import EvalRunRecord
from .agents import EvalCaseInput

router = APIRouter(dependencies=[Depends(principal)])
Rt: TypeAlias = Annotated[Runtime, Depends(runtime)]  # noqa: UP040 - FastAPI reads Annotated aliases
Me: TypeAlias = Annotated[Principal, Depends(principal)]  # noqa: UP040
Reader: TypeAlias = Annotated[Principal, Depends(reader_of("evals"))]  # noqa: UP040
PageNo: TypeAlias = Annotated[int, Query(alias="page", ge=1)]  # noqa: UP040
PageSize: TypeAlias = Annotated[int, Query(alias="pageSize", ge=1, le=200)]  # noqa: UP040
# A repeated filter; `_params` reads them from the request, these declare them in the API document.
Filter: TypeAlias = Annotated[list[str] | None, Query()]  # noqa: UP040


def _params(request: Request, page_no: int, size: int, search: str | None, facets: tuple[str, ...]) -> ListParams:
    """The shared list contract's parameters; each of `facets` filters by every value it is given."""
    wanted = {name: values for name in facets if (values := request.query_params.getlist(name))}
    params = ListParams(page=page_no, search=search, filters=wanted)
    # This route's own page size (up to 200), as the Evals page asks for it.
    return params.model_copy(update={"page_size": size})


@router.get("/v1/assurance/suites", response_model=Envelope[SuiteList])
async def list_suites(
    request: Request,
    rt: Rt,
    _: Reader,
    *,
    page_no: PageNo = 1,
    page_size: PageSize = 25,
    search: str | None = None,
    kind: Filter = None,
    tier: Filter = None,
    result: Filter = None,
) -> JSONResponse:
    """One suite per agent, skill or workflow in the acting team that has saved cases or a run, with the latest
    result of each case, by asset name then kind and id. Filters: `kind`, `tier`, `result` (failing, passing,
    not_run); each facet counts under the search and the other filters. A page past the end answers the last page."""
    params = _params(request, page_no, page_size, search, ("kind", "tier", "result"))
    return ok(await assurance.suites(rt, params))


@router.get("/v1/assurance/runs", response_model=Envelope[RunList])
async def list_runs(
    request: Request,
    rt: Rt,
    _: Reader,
    *,
    page_no: PageNo = 1,
    page_size: PageSize = 25,
    search: str | None = None,
    kind: Filter = None,
    trigger: Filter = None,
) -> JSONResponse:
    """Every stored run of the team's agents and skills and every test run of its workflows, newest first, then by
    id. Filters: `kind`, `trigger`."""
    return ok(await assurance.runs(rt, _params(request, page_no, page_size, search, ("kind", "trigger"))))


@router.get("/v1/assurance/gates", response_model=Envelope[GateList])
async def list_gates(
    request: Request,
    rt: Rt,
    _: Reader,
    *,
    page_no: PageNo = 1,
    page_size: PageSize = 25,
    search: str | None = None,
    tier: Filter = None,
    result: Filter = None,
) -> JSONResponse:
    """The publish checks of the team's publish requests, newest request first: each step's result and whether the
    request is blocked. Filters: `tier`, `result` (blocked, ready, decided)."""
    return ok(await assurance.gates(rt, _params(request, page_no, page_size, search, ("tier", "result"))))


class EvalCasesInput(In):
    cases: list[EvalCaseInput] = Field(default_factory=list[EvalCaseInput], max_length=200)


class SavedCaseContext(Out):
    collections: list[str] = Field(default_factory=list[str])


class SavedCaseCheck(Out):
    type: str
    tool: str | None = None
    text: str | None = None


class SavedCase(Out):
    id: str
    name: str
    input: str
    context: SavedCaseContext | None
    checks: list[SavedCaseCheck]
    status: str
    source: str
    reason: str
    created_by: str
    created_at: str


class SavedCases(Out):
    cases: list[SavedCase]


def _view(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "cases": [
            {
                "id": r["id"],
                "name": r["name"],
                "input": str(r["body"].get("input", "")),
                "context": r["body"].get("context"),
                "checks": r["body"].get("checks", []),
                "status": r["status"],
                "source": r["source"],
                "reason": r["reason"],
                "createdBy": r["created_by"],
                "createdAt": r["created_at"],
            }
            for r in rows
        ]
    }


async def _save(
    rt: Runtime, me: Principal, kind: str, asset_id: str, *, team_id: str, body: EvalCasesInput
) -> JSONResponse:
    can(caller_of(me), "evals", "run", team=team_id, what=f"the eval cases of {kind} {asset_id}")
    raw = [c.model_dump(by_alias=True) for c in body.cases]
    if raw:
        parse_cases(raw)
    store = EvalStore(rt.db)
    await store.replace_cases(kind, asset_id, team_id, raw, by=me.email)
    return ok(_view(await store.cases(kind, asset_id)))


@router.get("/v1/agents/{agent_id}/eval-cases", response_model=Envelope[SavedCases])
async def agent_cases(rt: Rt, _: Reader, __: Tx, agent_id: str) -> JSONResponse:
    """The agent's saved cases: the active ones its runs use, and drafts proposed from reviews."""
    await agent_registry(rt).row(agent_id)
    return ok(_view(await EvalStore(rt.db).cases(ASSET_AGENT, agent_id)))


@router.put("/v1/agents/{agent_id}/eval-cases", response_model=Envelope[SavedCases])
async def save_agent_cases(rt: Rt, me: Me, _: Tx, agent_id: str, body: EvalCasesInput) -> JSONResponse:
    """Replaces the agent's active cases with these. An unknown check type is 422 and nothing changes."""
    row = await agent_registry(rt).row(agent_id)
    return await _save(rt, me, ASSET_AGENT, agent_id, team_id=row.team_id, body=body)


@router.post("/v1/agents/{agent_id}/eval-cases", status_code=201, response_model=Envelope[SavedCases])
async def add_agent_cases(rt: Rt, me: Me, _: Tx, agent_id: str, body: EvalCasesInput) -> JSONResponse:
    """Adds these cases after the agent's last one and leaves the others, so two people adding at once each keep
    theirs; answers the saved set. No cases, or an unknown check type, is 422 and nothing changes."""
    row = await agent_registry(rt).row(agent_id)
    can(caller_of(me), "evals", "run", team=row.team_id, what=f"the eval cases of agent {agent_id}")
    raw = [c.model_dump(by_alias=True) for c in body.cases]
    parse_cases(raw)
    store = EvalStore(rt.db)
    await store.add_cases(ASSET_AGENT, agent_id, row.team_id, raw, by=me.email)
    return ok(_view(await store.cases(ASSET_AGENT, agent_id)), status=201)


@router.delete("/v1/eval-cases/{case_id}", status_code=204, response_class=Response)
async def delete_eval_case(rt: Rt, me: Me, _: Tx, case_id: str) -> Response:
    """Deletes one active case of an agent or a skill. Another team's case, a draft or one already gone is 404."""
    store = EvalStore(rt.db)
    row = await store.case(case_id)
    if row is None:
        raise NotFound("Eval case")
    asset = f"{row['kind']} {row['asset_id']}"
    can(caller_of(me), "evals", "run", team=str(row["team_id"]), what=f"the eval cases of {asset}")
    if not await store.remove_cases([case_id]):
        raise NotFound("Eval case")
    return Response(status_code=204)


@router.get("/v1/agents/{agent_id}/eval-runs", response_model=Envelope[ListResult[EvalRunRecord]])
async def agent_eval_runs(rt: Rt, _: Reader, __: Tx, agent_id: str, q: ListQuery) -> JSONResponse:
    """The agent's kept runs on the shared list contract, newest first, then by id. Each row carries its case
    results, so the tab opens a run without another request."""
    await agent_registry(rt).row(agent_id)
    page = await EvalStore(rt.db).runs_page(ASSET_AGENT, agent_id, q)
    return ok({**page, "data": [stored_run(r) for r in page["data"]]})


@router.get("/v1/eval-runs/{run_id}", response_model=Envelope[EvalRunRecord])
async def eval_run(rt: Rt, _: Reader, __: Tx, run_id: str) -> JSONResponse:
    """One kept run of an agent with each case's result. Another team's run is 404."""
    row = await EvalStore(rt.db).run(run_id)
    if row is None or row["kind"] != ASSET_AGENT:
        raise NotFound("Eval run")
    return ok(stored_run(row))


@router.get("/v1/skills/{skill_id}/eval-cases", response_model=Envelope[SavedCases])
async def skill_cases(rt: Rt, _: Reader, __: Tx, skill_id: str) -> JSONResponse:
    await SkillRegistry(rt.db).row(skill_id)
    return ok(_view(await EvalStore(rt.db).cases(ASSET_SKILL, skill_id)))


@router.put("/v1/skills/{skill_id}/eval-cases", response_model=Envelope[SavedCases])
async def save_skill_cases(rt: Rt, me: Me, _: Tx, skill_id: str, body: EvalCasesInput) -> JSONResponse:
    row = await SkillRegistry(rt.db).row(skill_id)
    return await _save(rt, me, ASSET_SKILL, skill_id, team_id=row.team_id, body=body)


def active(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The case bodies a run uses."""
    return [r["body"] for r in rows if r["status"] == CASE_ACTIVE]
