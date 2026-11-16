"""/v1/assurance: the Evals page's suites, runs and publish checks, and the saved cases on an agent or a skill.

The saved-case routes answer in one request transaction (`Tx`), so a replace and the cases read back are one moment.
The three lists take none: each names every asset's team through platform-service (`team_name`) while it builds the
snapshot, and no connection is held while that answers. They page that snapshot in memory rather than in SQL, because
each row is computed from several stores (an asset's cases, its latest run and its publish requests).
"""

from __future__ import annotations

from typing import Annotated, Any, TypeAlias

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import Field

from ops_access import can
from ops_agents.app.evals import parse_cases
from ops_agents.domain.evals import ASSET_AGENT, ASSET_SKILL, CASE_ACTIVE
from ops_identity.fastapi import Tx
from ops_service_kit.http import Envelope, In, Out

from ...store.evals import EvalStore
from ...store.skills import SkillRegistry
from ..agent_registry import registry as agent_registry
from ..assurance import Snapshot, snapshot
from ..assurance_schemas import GateList, RunList, SuiteList
from ..auth import Principal, caller_of, principal, reader_of
from ..deps import Runtime, runtime
from ..envelope import ok
from ..hitl_facade import page
from .agents import EvalCaseInput

router = APIRouter(dependencies=[Depends(principal)])
Rt: TypeAlias = Annotated[Runtime, Depends(runtime)]  # noqa: UP040 - FastAPI reads Annotated aliases
Me: TypeAlias = Annotated[Principal, Depends(principal)]  # noqa: UP040
Reader: TypeAlias = Annotated[Principal, Depends(reader_of("evals"))]  # noqa: UP040
PageNo: TypeAlias = Annotated[int, Query(alias="page", ge=1)]  # noqa: UP040
PageSize: TypeAlias = Annotated[int, Query(alias="pageSize", ge=1, le=200)]  # noqa: UP040
# A repeated filter; `_answer` reads them from the request, these declare them in the API document.
Filter: TypeAlias = Annotated[list[str] | None, Query()]  # noqa: UP040

SUITE_FACETS = ("kind", "tier", "result")
RUN_FACETS = ("kind", "trigger")
GATE_FACETS = ("tier", "result")


def _suite_result(s: dict[str, Any]) -> str:
    if s["passRate"] is None:
        return "not_run"
    return "failing" if s["failing"] else "passing"


def _gate_result(g: dict[str, Any]) -> str:
    if g["blocked"]:
        return "blocked"
    return "ready" if g["reviewStatus"] == "pending" else "decided"


def _columns(row: dict[str, Any], tab: str) -> dict[str, str]:
    if tab == "suites":
        return {"kind": row["asset"]["kind"], "tier": row["tier"], "result": _suite_result(row)}
    if tab == "runs":
        return {"kind": row["asset"]["kind"], "trigger": row["trigger"]}
    return {"tier": row["tier"], "result": _gate_result(row)}


def _answer(
    request: Request, snap: Snapshot, tab: str, *, columns: tuple[str, ...], page_no: int, size: int, search: str | None
) -> JSONResponse:
    rows: list[dict[str, Any]] = getattr(snap, tab)
    needle = (search or request.query_params.get("q") or "").strip().lower()
    if needle:
        rows = [r for r in rows if needle in r["asset"]["name"].lower()]
    facets: dict[str, dict[str, int]] = {c: {} for c in columns}
    for r in rows:
        for c, v in _columns(r, tab).items():
            facets[c][v] = facets[c].get(v, 0) + 1
    for c in columns:
        if wanted := request.query_params.getlist(c):
            rows = [r for r in rows if _columns(r, tab)[c] in wanted]
    return ok(
        {
            **page(rows, page_no, size),
            "facets": facets,
            "stats": snap.stats,
            "tabCounts": snap.counts,
        }
    )


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
    result of each case. Filters: `kind`, `tier`, `result` (failing, passing, not_run)."""
    return _answer(
        request, await snapshot(rt), "suites", columns=SUITE_FACETS, page_no=page_no, size=page_size, search=search
    )


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
    """Every stored run of the team's agents and skills and every test run of its workflows, newest first."""
    return _answer(
        request, await snapshot(rt), "runs", columns=RUN_FACETS, page_no=page_no, size=page_size, search=search
    )


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
    """The publish checks of the team's publish requests: each step's result and whether the request is blocked."""
    return _answer(
        request, await snapshot(rt), "gates", columns=GATE_FACETS, page_no=page_no, size=page_size, search=search
    )


class EvalCasesInput(In):
    cases: list[EvalCaseInput] = Field(default_factory=list[EvalCaseInput], max_length=200)


class SavedCase(Out):
    id: str
    name: str
    input: str
    context: dict[str, Any] | None
    checks: list[dict[str, Any]]
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
    return await _save(rt, me, ASSET_AGENT, agent_id, team_id=row["team_id"], body=body)


@router.get("/v1/skills/{skill_id}/eval-cases", response_model=Envelope[SavedCases])
async def skill_cases(rt: Rt, _: Reader, __: Tx, skill_id: str) -> JSONResponse:
    await SkillRegistry(rt.db).row(skill_id)
    return ok(_view(await EvalStore(rt.db).cases(ASSET_SKILL, skill_id)))


@router.put("/v1/skills/{skill_id}/eval-cases", response_model=Envelope[SavedCases])
async def save_skill_cases(rt: Rt, me: Me, _: Tx, skill_id: str, body: EvalCasesInput) -> JSONResponse:
    row = await SkillRegistry(rt.db).row(skill_id)
    return await _save(rt, me, ASSET_SKILL, skill_id, team_id=row["team_id"], body=body)


def active(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The case bodies a run uses."""
    return [r["body"] for r in rows if r["status"] == CASE_ACTIVE]
