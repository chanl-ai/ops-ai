"""What the Evals page reads: the acting team's suites, runs and publish checks a page at a time, joined with the
names the page shows, so the console joins nothing. Each list, its facets, total and the page's figures come from SQL
(`store/assurance_list.py`) in one transaction; the owner team names are read from platform-service after it closes,
for the page's teams only."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

from ops_agents.domain.evals import (
    ASSET_AGENT,
    ASSET_SKILL,
    ASSET_WORKFLOW,
    DEFAULT_TIER,
    MODE_BLOCKING,
    STEP_FAIL,
    STEP_PASS,
    STEP_PENDING,
    pass_rate,
    step_mode,
)
from ops_service_kit.listing import ListParams

from ..store.assurance_list import Checks, Listed, Stats, read_list
from .deps import Runtime
from .team_names import team_name

HREF = {ASSET_AGENT: "/build/agents", ASSET_SKILL: "/build/skills", ASSET_WORKFLOW: "/build/workflows"}
PASS, FAIL = "pass", "fail"
STEP_LABELS = {"structural": "Structure checks", "pass_rate": "Pass rate", "regressions": "Regressions"}
OPEN_STATUS = "pending"
REVIEW_STATUSES = ("pending", "approved", "rejected", "returned")


def _asset(row: dict[str, Any]) -> dict[str, Any]:
    kind, asset_id = str(row["kind"]), str(row["asset_id"])
    return {"kind": kind, "id": asset_id, "name": str(row["name"]), "href": f"{HREF[kind]}/{asset_id}"}


def _outcome(value: Any) -> str | None:
    status = cast(dict[str, Any], value).get("status") if isinstance(value, dict) else None
    return (PASS if status == PASS else FAIL) if status else None


def _figures(s: Stats) -> dict[str, Any]:
    return {
        "stats": {
            "failingSuites": s.failing_suites,
            "gatesBlocked": s.gates_blocked,
            "liveUntested": s.live_untested,
            "notRun": s.not_run,
        },
        "tabCounts": {"suites": s.suites, "runs": s.runs, "gates": s.gates},
    }


Shape = Callable[[dict[str, Any], Listed, float], dict[str, Any]]


def _checks(rt: Runtime) -> Checks:
    blocking = frozenset(step for step in STEP_LABELS if step_mode(DEFAULT_TIER, step) == MODE_BLOCKING)
    return Checks(tier=DEFAULT_TIER, blocking=blocking, min_pass_rate=rt.settings.eval_min_pass_rate)


async def _answer(rt: Runtime, tab: str, params: ListParams, shape: Shape) -> dict[str, Any]:
    """Reads the page, its extras and the figures in one transaction, then names the page's teams with none open."""
    checks = _checks(rt)
    listed = await read_list(rt.db, tab, params, checks)
    rows = cast(list[dict[str, Any]], listed.page["data"])
    teams: dict[str, str] = {}
    for team in sorted({str(r["team_id"]) for r in rows if r.get("team_id")}):
        teams[team] = (await team_name(rt, team))["teamName"] or team
    data = [{**shape(row, listed, checks.min_pass_rate), **_owner(row, teams, tab)} for row in rows]
    return {**listed.page, "data": data, **_figures(listed.stats)}


def _owner(row: dict[str, Any], teams: dict[str, str], tab: str) -> dict[str, Any]:
    return {"owner": teams.get(str(row["team_id"]), str(row["team_id"]))} if tab == "suites" else {}


async def suites(rt: Runtime, params: ListParams) -> dict[str, Any]:
    """One suite per agent, skill or workflow with saved cases or a run, with its newest run's case results."""
    return await _answer(rt, "suites", params, _suite)


def _suite(row: dict[str, Any], listed: Listed, _minimum: float) -> dict[str, Any]:
    kind, asset_id = str(row["kind"]), str(row["asset_id"])
    details = listed.extras[f"{kind}:{asset_id}"]
    ran = row["run_id"] is not None
    passed, total = int(row["passed"] or 0), int(row["total"] or 0)
    workflow = kind == ASSET_WORKFLOW
    results = [
        {
            "caseId": str(x.get("caseId", i)) if workflow else str(i),
            "name": str(x.get("caseName", x.get("name", ""))) if workflow else x["caseName"],
            "candidate": _outcome(x.get("draft")) or FAIL,
            "live": _outcome(x.get("live")),
            "regression": bool(x.get("regression")),
            "humanVerdict": None,
        }
        for i, x in enumerate(cast(list[dict[str, Any]], details.results))
    ]
    return {
        "id": f"{kind}:{asset_id}",
        "asset": _asset(row),
        "owner": "",
        "tier": row["tier"],
        "cases": int(row["cases"]),
        "draftCases": int(row["draft_cases"]),
        "passRate": pass_rate(passed, total) if ran else None,
        "livePassRate": pass_rate(int(row["live_passed"]), total) if ran and row["live_passed"] is not None else None,
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


async def runs(rt: Runtime, params: ListParams) -> dict[str, Any]:
    """Every stored run of the team's agents and skills and every test run of its workflows, newest first."""

    return await _answer(rt, "runs", params, _run)


def _run(row: dict[str, Any], _listed: Listed, _minimum: float) -> dict[str, Any]:
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


async def gates(rt: Runtime, params: ListParams) -> dict[str, Any]:
    """The publish checks of the team's publish requests: each step's result and whether the request is blocked."""
    return await _answer(rt, "gates", params, _gate)


def _gate(row: dict[str, Any], _listed: Listed, minimum: float) -> dict[str, Any]:
    version, tier = int(row["version"]), str(row["tier"])
    steps: list[dict[str, Any]] = []

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
                f"{failing} structure checks fail." if failing else "Every structure check passes.",
            )
    passed, total, regressions = int(row["passed"]), int(row["total"]), int(row["regressions"])
    if not summarised or total == 0:
        pending = f"No saved cases have run on version {version}."
        add("pass_rate", STEP_PENDING, pending)
        add("regressions", STEP_PENDING, pending)
    else:
        ok_rate = passed / total >= float(minimum)
        add(
            "pass_rate",
            STEP_PASS if ok_rate else STEP_FAIL,
            f"{passed} of {total} cases pass"
            + ("." if ok_rate else f"; at least {round(float(minimum) * 100)}% must."),
        )
        add(
            "regressions",
            STEP_FAIL if regressions else STEP_PASS,
            f"{regressions} cases pass on the live version and fail on this one."
            if regressions
            else "No case that passes live fails here.",
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
