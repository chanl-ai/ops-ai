"""What the Evals page reads: the acting team's suites, runs and publish checks a page at a time, joined with the
names the page shows, so the console joins nothing. Each list, its facets, total and the page's figures come from SQL
(`store/assurance_list.py`) in one transaction; the owner team names are read from platform-service after it closes,
for the page's teams only."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypedDict, cast

from ops_agents.domain.evals import (
    ASSET_AGENT,
    ASSET_SKILL,
    ASSET_WORKFLOW,
    STEP_FAIL,
    STEP_PASS,
    STEP_PENDING,
    pass_rate,
    step_mode,
)
from ops_service_kit.http import Json, JsonValue
from ops_service_kit.listing import ListParams
from ops_store import isolation

from ..store.assurance_list import Checks, Listed, Stats, read_list
from .deps import Runtime
from .eval_gate import STEP_LABELS, GateStep, checks_of, eval_steps, evals_required
from .team_names import team_name

HREF = {ASSET_AGENT: "/build/agents", ASSET_SKILL: "/build/skills", ASSET_WORKFLOW: "/build/workflows"}
PASS, FAIL = "pass", "fail"
OPEN_STATUS = "pending"
REVIEW_STATUSES = ("pending", "approved", "rejected", "returned")


# A figure as SQL paged it, read with int() or float() as it always was.
Figure = int | float | str


class AssetRow(TypedDict):
    """The columns every Evals list selects for the asset a row is about."""

    kind: JsonValue
    asset_id: JsonValue
    name: JsonValue


class SuiteRow(AssetRow):
    """A suites row (store/assurance_list.py suites_page); the run's columns are None when no run exists."""

    team_id: JsonValue
    tier: JsonValue
    run_id: JsonValue
    version: JsonValue
    live_version: JsonValue
    passed: Figure | None
    total: Figure | None
    live_passed: Figure | None
    regressions: Figure
    ran_at: JsonValue
    cases: Figure
    draft_cases: Figure


class RunRow(AssetRow):
    """A runs row (store/assurance_list.py)."""

    id: JsonValue
    version: Figure
    trigger: JsonValue
    passed: Figure
    total: Figure
    regressions: Figure
    duration_ms: Figure
    cost_usd: Figure
    ran_at: JsonValue


class GateRow(AssetRow):
    """A gates row (store/assurance_list.py): a publish request with its newest summary's figures."""

    id: JsonValue
    published_version: int | None
    version: Figure
    status: JsonValue
    requested_by: JsonValue
    created_at: JsonValue
    tier: JsonValue
    summary_id: JsonValue
    passed: Figure
    total: Figure
    regressions: Figure
    checks_failing: Figure | None
    cases: Figure
    pass_rate_result: str
    regressions_result: str
    stale: JsonValue
    blocked: JsonValue


class AssetRef(TypedDict):
    kind: str
    id: str
    name: str
    href: str


class CaseResult(TypedDict):
    caseId: str
    name: JsonValue
    candidate: str
    live: str | None
    regression: bool
    humanVerdict: None


class DraftCase(TypedDict):
    id: str
    name: str
    input: str
    source: str
    status: str
    reviewId: str
    reason: str
    createdBy: str
    createdAt: str


class SuiteView(TypedDict):
    """A suite as the Evals page reads it, in reply order."""

    id: str
    asset: AssetRef
    owner: str
    tier: JsonValue
    cases: int
    draftCases: int
    passRate: float | None
    livePassRate: float | None
    regressions: int | None
    candidateVersion: JsonValue
    liveVersion: JsonValue
    lastRunAt: JsonValue
    failing: bool
    results: list[CaseResult]
    drafts: list[DraftCase]


class RunView(TypedDict):
    """A run as the Evals page reads it, in reply order."""

    id: JsonValue
    asset: AssetRef
    version: int
    trigger: JsonValue
    passed: int
    total: int
    passRate: float
    regressions: int
    durationMs: int
    costUsd: float
    ranAt: JsonValue
    reviewId: None


class GateView(TypedDict):
    """A publish request's checks as the Evals page reads them, in reply order."""

    reviewId: JsonValue
    asset: AssetRef
    fromVersion: int | None
    toVersion: int
    tier: str
    requestedBy: JsonValue
    requestedAt: JsonValue
    reviewStatus: str
    steps: list[GateStep]
    blocked: bool


def _asset(row: AssetRow) -> AssetRef:
    kind, asset_id = str(row["kind"]), str(row["asset_id"])
    return {"kind": kind, "id": asset_id, "name": str(row["name"]), "href": f"{HREF[kind]}/{asset_id}"}


def _outcome(value: JsonValue) -> str | None:
    status = value.get("status") if isinstance(value, dict) else None
    return (PASS if status == PASS else FAIL) if status else None


def _figures(s: Stats) -> Json:
    return {
        "stats": {
            "failingSuites": s.failing_suites,
            "gatesBlocked": s.gates_blocked,
            "liveUntested": s.live_untested,
            "notRun": s.not_run,
        },
        "tabCounts": {"suites": s.suites, "runs": s.runs, "gates": s.gates},
    }


async def _checks(rt: Runtime) -> Checks:
    """The acting team's checks, with its evalsRequired read as a publish reads it: a setting that cannot be read
    counts as on, as the publish refuses then."""
    required = await evals_required(rt, isolation.team())
    return checks_of(rt, required=required is not False)


async def _answer[R: AssetRow, V](
    rt: Runtime, tab: str, params: ListParams, shape: Callable[[R, Listed, float, dict[str, str]], V]
) -> dict[str, JsonValue | list[V]]:
    """Reads the page, its extras and the figures in one transaction, then names the page's teams with none open.
    `shape` is given the page's team names, which a suite shows as its owner."""
    checks = await _checks(rt)
    listed = await read_list(rt.db, tab, params, checks)
    # The tab's columns as its page query selects them (store/assurance_list.py).
    rows = cast(list[R], listed.page["data"])
    teams: dict[str, str] = {}
    # Any tab's row may name a team; only a suite shows it.
    for team in sorted({str(cast(Json, r).get("team_id")) for r in rows if cast(Json, r).get("team_id")}):
        teams[team] = (await team_name(rt, team))["teamName"] or team
    data = [shape(row, listed, checks.min_pass_rate, teams) for row in rows]
    return {**listed.page, "data": data, **_figures(listed.stats)}


async def suites(rt: Runtime, params: ListParams) -> dict[str, JsonValue | list[SuiteView]]:
    """One suite per agent, skill or workflow with saved cases or a run, with its newest run's case results."""
    return await _answer(rt, "suites", params, _suite)


def _suite(row: SuiteRow, listed: Listed, _minimum: float, teams: dict[str, str]) -> SuiteView:
    kind, asset_id = str(row["kind"]), str(row["asset_id"])
    details = listed.extras[f"{kind}:{asset_id}"]
    ran = row["run_id"] is not None
    passed, total = int(row["passed"] or 0), int(row["total"] or 0)
    workflow = kind == ASSET_WORKFLOW
    results: list[CaseResult] = [
        {
            "caseId": str(x.get("caseId", i)) if workflow else str(i),
            "name": str(x.get("caseName", x.get("name", ""))) if workflow else x["caseName"],
            "candidate": _outcome(x.get("draft")) or FAIL,
            "live": _outcome(x.get("live")),
            "regression": bool(x.get("regression")),
            "humanVerdict": None,
        }
        for i, x in enumerate(cast(list[Json], details.results))
    ]
    team = str(row["team_id"])
    return {
        "id": f"{kind}:{asset_id}",
        "asset": _asset(row),
        "owner": teams.get(team, team),
        "tier": row["tier"],
        "cases": int(row["cases"]),
        "draftCases": int(row["draft_cases"]),
        "passRate": pass_rate(passed, total) if ran else None,
        "livePassRate": pass_rate(int(live), total) if ran and (live := row["live_passed"]) is not None else None,
        "regressions": int(row["regressions"]) if ran else None,
        "candidateVersion": row["version"] if ran else None,
        "liveVersion": row["live_version"] if ran else None,
        "lastRunAt": row["ran_at"] if ran else None,
        "failing": ran and passed < total,
        "results": results,
        "drafts": [
            {
                "id": d.id,
                "name": d.name,
                "input": d.input,
                "source": "review",
                "status": "draft",
                "reviewId": d.review_id or "",
                "reason": d.reason,
                "createdBy": d.created_by,
                "createdAt": d.created_at,
            }
            for d in details.drafts
        ],
    }


async def runs(rt: Runtime, params: ListParams) -> dict[str, JsonValue | list[RunView]]:
    """Every stored run of the team's agents and skills and every test run of its workflows, newest first."""

    return await _answer(rt, "runs", params, _run)


def _run(row: RunRow, _listed: Listed, _minimum: float, _teams: dict[str, str]) -> RunView:
    passed, total = int(row["passed"]), int(row["total"])
    return {
        "id": row["id"],
        "asset": _asset(row),
        "version": int(row["version"]),
        "trigger": row["trigger"],
        "passed": passed,
        "total": total,
        "passRate": pass_rate(passed, total) or 0.0,
        "regressions": int(row["regressions"]),
        "durationMs": int(row["duration_ms"]),
        "costUsd": float(row["cost_usd"]),
        "ranAt": row["ran_at"],
        "reviewId": None,
    }


async def gates(rt: Runtime, params: ListParams) -> dict[str, JsonValue | list[GateView]]:
    """The publish checks of the team's publish requests: each step's result and whether the request is blocked."""
    return await _answer(rt, "gates", params, _gate)


def _gate(row: GateRow, _listed: Listed, minimum: float, _teams: dict[str, str]) -> GateView:
    version, tier = int(row["version"]), str(row["tier"])
    steps: list[GateStep] = []

    def add(step: str, result: str, detail: str) -> None:
        steps.append(
            {
                "step": step,
                "label": STEP_LABELS[step],
                "mode": step_mode(tier, step),
                "result": result,
                "detail": detail,
            }
        )

    summarised = row["summary_id"] is not None
    if row["kind"] == ASSET_WORKFLOW:
        if not summarised:
            add("structural", STEP_PENDING, "No test run of this workflow yet.")
        else:
            failing = int(row["checks_failing"] or 0)
            add(
                "structural",
                STEP_FAIL if failing else STEP_PASS,
                ("1 structure check fails." if failing == 1 else f"{failing} structure checks fail.")
                if failing
                else "Every structure check passes.",
            )
    # The step results are the store's rule (`assurance_list._eval_steps`); this only words them.
    steps.extend(
        eval_steps(
            tier,
            float(minimum),
            version,
            passed=int(row["passed"]),
            total=int(row["total"]),
            regressions=int(row["regressions"]),
            pass_rate_result=row["pass_rate_result"],
            regressions_result=row["regressions_result"],
            stale=bool(row["stale"]),
        )
    )
    published = row["published_version"]
    status = str(row["status"])
    return {
        "reviewId": row["id"],
        "asset": _asset(row),
        "fromVersion": published if published is not None and published < version else None,
        "toVersion": version,
        "tier": tier,
        "requestedBy": row["requested_by"],
        "requestedAt": row["created_at"],
        "reviewStatus": status if status in REVIEW_STATUSES else OPEN_STATUS,
        "steps": steps,
        "blocked": bool(row["blocked"]),
    }
