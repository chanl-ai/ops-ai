"""What the Evals page reads: one snapshot of the acting team's suites, runs and publish checks, joined with the
names the page shows, so the console joins nothing. Agents and skills come from the saved cases and runs
(`store/evals.py`); a workflow's runs are its stored test runs; publish checks come from the publish requests."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, cast

from ops_agents.domain.evals import (
    ASSET_AGENT,
    ASSET_SKILL,
    ASSET_WORKFLOW,
    CASE_ACTIVE,
    CASE_DRAFT,
    DEFAULT_TIER,
    STEP_FAIL,
    STEP_PASS,
    STEP_PENDING,
    TRIGGER_MANUAL,
    pass_rate,
    step_mode,
)

from ..store.evals import EvalStore
from ..store.skill_names import SkillNames
from ..store.skills import SkillRegistry
from .agent_registry import registry as agent_registry
from .deps import Runtime
from .team_names import team_name
from .workflow_registry import registry as workflow_registry

HREF = {ASSET_AGENT: "/build/agents", ASSET_SKILL: "/build/skills", ASSET_WORKFLOW: "/build/workflows"}
PASS, FAIL = "pass", "fail"
STEP_LABELS = {"structural": "Structure checks", "pass_rate": "Pass rate", "regressions": "Regressions"}
OPEN_STATUS = "pending"


def _asset(kind: str, asset_id: str, name: str) -> dict[str, Any]:
    return {"kind": kind, "id": asset_id, "name": name, "href": f"{HREF[kind]}/{asset_id}"}


def _outcome(value: Any) -> str | None:
    status = cast(dict[str, Any], value).get("status") if isinstance(value, dict) else None
    return (PASS if status == PASS else FAIL) if status else None


@dataclass
class Snapshot:
    suites: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    runs: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    gates: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    stats: dict[str, int] = field(default_factory=dict[str, int])

    @property
    def counts(self) -> dict[str, int]:
        return {"suites": len(self.suites), "runs": len(self.runs), "gates": len(self.gates)}


async def snapshot(rt: Runtime) -> Snapshot:
    """Everything the acting team sees, read once for a request."""
    store = EvalStore(rt.db)
    agents_reg, skills_reg, workflows_reg = agent_registry(rt), SkillRegistry(rt.db), workflow_registry(rt)
    agents = {str(r["id"]): r for r in await agents_reg.rows()}
    skills = {str(r["id"]): r for r in await skills_reg.rows()}
    workflows = {str(r["id"]): r for r in await workflows_reg.rows()}
    cases, runs = await store.cases(), await store.runs()
    validations = await workflows_reg.validations(set(workflows))

    agent_names = await agents_reg.named_versions({(i, int(r["version"])) for i, r in agents.items()})
    names: dict[tuple[str, str], str] = {
        (ASSET_AGENT, i): agent_names.get((i, int(r["version"])), (str(r["slug"]), ""))[0] for i, r in agents.items()
    }
    skill_names = await SkillNames(rt.db).newest(set(skills))
    names |= {(ASSET_SKILL, i): skill_names.get(i) or str(r["slug"]) for i, r in skills.items()}
    names |= {(ASSET_WORKFLOW, i): str(r["name"]) for i, r in workflows.items()}
    teams = (
        {(ASSET_AGENT, i): str(r["team_id"]) for i, r in agents.items()}
        | {(ASSET_SKILL, i): str(r["team_id"]) for i, r in skills.items()}
        | {(ASSET_WORKFLOW, i): str(r["team_id"]) for i, r in workflows.items()}
    )
    team_labels: dict[str, str] = {}
    for team in set(teams.values()):
        team_labels[team] = (await team_name(rt, team))["teamName"] or team

    def asset(kind: str, asset_id: str) -> dict[str, Any]:
        return _asset(kind, asset_id, names[(kind, asset_id)])

    latest_run: dict[tuple[str, str], dict[str, Any]] = {}
    for r in runs:  # newest first
        latest_run.setdefault((str(r["kind"]), str(r["asset_id"])), r)
    latest_validation: dict[str, dict[str, Any]] = {}
    for v in validations:
        latest_validation.setdefault(str(v["workflow_id"]), v)

    snap = Snapshot()
    kept = {key for key in latest_run if key in names} | {(str(c["kind"]), str(c["asset_id"])) for c in cases}
    for kind, asset_id in sorted(k for k in kept if k in names):
        mine = [c for c in cases if (c["kind"], c["asset_id"]) == (kind, asset_id)]
        active = [c for c in mine if c["status"] == CASE_ACTIVE]
        drafts = [c for c in mine if c["status"] == CASE_DRAFT]
        run = latest_run.get((kind, asset_id))
        total = int(run["total"]) if run else 0
        results = [
            {
                "caseId": str(i),
                "name": x["caseName"],
                "candidate": _outcome(x["draft"]) or FAIL,
                "live": _outcome(x.get("live")),
                "regression": bool(x.get("regression")),
                "humanVerdict": None,
            }
            for i, x in enumerate(run["results"] if run else [])
        ]
        snap.suites.append(
            {
                "id": f"{kind}:{asset_id}",
                "asset": asset(kind, asset_id),
                "owner": team_labels[teams[(kind, asset_id)]],
                "tier": DEFAULT_TIER,
                "cases": len(active),
                "draftCases": len(drafts),
                "passRate": pass_rate(int(run["passed"]), total) if run else None,
                "livePassRate": pass_rate(int(run["live_passed"]), total)
                if run and run["live_passed"] is not None
                else None,
                "regressions": int(run["regressions"]) if run else None,
                "candidateVersion": int(run["version"]) if run else None,
                "liveVersion": run["live_version"] if run else None,
                "lastRunAt": run["ran_at"] if run else None,
                "failing": bool(run) and int(run["passed"]) < total,
                "results": results,
                "drafts": [
                    {
                        "id": d["id"],
                        "name": d["name"],
                        "input": str(d["body"].get("input", "")),
                        "source": "review",
                        "status": "draft",
                        "reviewId": d["review_id"] or "",
                        "reason": d["reason"],
                        "createdBy": d["created_by"],
                        "createdAt": d["created_at"],
                    }
                    for d in drafts
                ],
            }
        )
    for wid, v in sorted(latest_validation.items()):
        summary = v["summary"]
        total, passed = int(summary["total"]), int(summary["passed"])
        snap.suites.append(
            {
                "id": f"{ASSET_WORKFLOW}:{wid}",
                "asset": asset(ASSET_WORKFLOW, wid),
                "owner": team_labels[teams[(ASSET_WORKFLOW, wid)]],
                "tier": DEFAULT_TIER,
                "cases": total,
                "draftCases": 0,
                "passRate": pass_rate(passed, total),
                "livePassRate": None,
                "regressions": int(summary.get("regressions", 0)),
                "candidateVersion": workflows[wid]["published_version"],
                "liveVersion": workflows[wid]["published_version"],
                "lastRunAt": v["ran_at"],
                "failing": passed < total,
                "results": [
                    {
                        "caseId": str(x.get("caseId", i)),
                        "name": str(x.get("caseName", x.get("name", ""))),
                        "candidate": _outcome(x.get("draft")) or FAIL,
                        "live": _outcome(x.get("live")),
                        "regression": bool(x.get("regression")),
                        "humanVerdict": None,
                    }
                    for i, x in enumerate(v["results"])
                ],
                "drafts": [],
            }
        )
    snap.suites.sort(key=lambda s: (s["asset"]["name"].lower(), s["id"]))

    for r in runs:
        key = (str(r["kind"]), str(r["asset_id"]))
        if key not in names:
            continue
        total = int(r["total"])
        snap.runs.append(
            {
                "id": r["id"],
                "asset": asset(*key),
                "version": int(r["version"]),
                "trigger": r["trigger"],
                "passed": int(r["passed"]),
                "total": total,
                "passRate": pass_rate(int(r["passed"]), total) or 0.0,
                "regressions": int(r["regressions"]),
                "durationMs": int(r["duration_ms"]),
                "costUsd": float(r["cost_usd"]),
                "ranAt": r["ran_at"],
                "reviewId": None,
            }
        )
    for v in validations:
        summary, total = v["summary"], int(v["summary"]["total"])
        wid = str(v["workflow_id"])
        snap.runs.append(
            {
                "id": v["id"],
                "asset": asset(ASSET_WORKFLOW, wid),
                "version": int(workflows[wid]["published_version"] or 0),
                "trigger": TRIGGER_MANUAL,
                "passed": int(summary["passed"]),
                "total": total,
                "passRate": pass_rate(int(summary["passed"]), total) or 0.0,
                "regressions": int(summary.get("regressions", 0)),
                "durationMs": 0,
                "costUsd": 0.0,
                "ranAt": v["ran_at"],
                "reviewId": None,
            }
        )
    snap.runs.sort(key=lambda r: (r["ranAt"], r["id"]), reverse=True)

    by_version: dict[tuple[str, str, int], dict[str, Any]] = {}
    for r in runs:
        by_version.setdefault((str(r["kind"]), str(r["asset_id"]), int(r["version"])), r)
    for q in await agents_reg.all_requests():
        kind, subject = str(q["kind"]), str(q["subject_id"])
        if (kind, subject) not in names or kind not in HREF:
            continue
        snap.gates.append(
            _gate(
                rt,
                q,
                kind,
                asset=asset(kind, subject),
                by_version=by_version,
                validation=latest_validation.get(subject),
                published=_published(kind, subject, agents, skills, workflows),
            )
        )
    snap.stats = _stats(
        snap,
        latest_run=latest_run,
        latest_validation=latest_validation,
        agents=agents,
        skills=skills,
        workflows=workflows,
        cases=cases,
    )
    return snap


def _published(
    kind: str, subject: str, agents: dict[str, Any], skills: dict[str, Any], workflows: dict[str, Any]
) -> int | None:
    found = {ASSET_AGENT: agents, ASSET_SKILL: skills, ASSET_WORKFLOW: workflows}[kind].get(subject)
    return found["published_version"] if found else None


def _gate(
    rt: Runtime,
    q: dict[str, Any],
    kind: str,
    *,
    asset: dict[str, Any],
    by_version: dict[tuple[str, str, int], dict[str, Any]],
    validation: dict[str, Any] | None,
    published: int | None,
) -> dict[str, Any]:
    version = int(q["version"])
    tier = DEFAULT_TIER
    minimum = rt.settings.eval_min_pass_rate
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

    if kind == ASSET_WORKFLOW:
        summary = validation["summary"] if validation else None
        if summary is None:
            add("structural", STEP_PENDING, "No test run of this workflow yet.")
        else:
            failing = int(summary.get("checksFailing", 0))
            add(
                "structural",
                STEP_FAIL if failing else STEP_PASS,
                f"{failing} structure checks fail." if failing else "Every structure check passes.",
            )
        passed, total, regressions = (
            (int(summary["passed"]), int(summary["total"]), int(summary.get("regressions", 0)))
            if summary
            else (0, 0, 0)
        )
    else:
        run = by_version.get((kind, str(q["subject_id"]), version))
        passed, total, regressions = (
            (int(run["passed"]), int(run["total"]), int(run["regressions"])) if run else (0, 0, 0)
        )
        summary = run
    if summary is None or total == 0:
        pending = f"No saved cases have run on version {version}."
        add("pass_rate", STEP_PENDING, pending)
        add("regressions", STEP_PENDING, pending)
    else:
        rate = passed / total
        ok_rate = rate >= minimum
        add(
            "pass_rate",
            STEP_PASS if ok_rate else STEP_FAIL,
            f"{passed} of {total} cases pass" + ("." if ok_rate else f"; at least {round(minimum * 100)}% must."),
        )
        add(
            "regressions",
            STEP_FAIL if regressions else STEP_PASS,
            f"{regressions} cases pass on the live version and fail on this one."
            if regressions
            else "No case that passes live fails here.",
        )
    opened = q["status"] == OPEN_STATUS
    return {
        "reviewId": q["id"],
        "asset": asset,
        "fromVersion": published if published is not None and published < version else None,
        "toVersion": version,
        "tier": tier,
        "requestedBy": q["requested_by"],
        "requestedAt": q["created_at"],
        "reviewStatus": q["status"] if q["status"] in ("pending", "approved", "rejected", "returned") else "pending",
        "steps": steps,
        "blocked": opened and any(s["mode"] == "blocking" and s["result"] == STEP_FAIL for s in steps),
    }


def _stats(
    snap: Snapshot,
    *,
    latest_run: dict[tuple[str, str], dict[str, Any]],
    latest_validation: dict[str, dict[str, Any]],
    agents: dict[str, Any],
    skills: dict[str, Any],
    workflows: dict[str, Any],
    cases: list[dict[str, Any]],
) -> dict[str, int]:
    def passing(kind: str, asset_id: str) -> bool:
        if kind == ASSET_WORKFLOW:
            v = latest_validation.get(asset_id)
            return (
                bool(v) and int(v["summary"]["total"]) > 0 and int(v["summary"]["passed"]) == int(v["summary"]["total"])
            )
        r = latest_run.get((kind, asset_id))
        return bool(r) and int(r["total"]) > 0 and int(r["passed"]) == int(r["total"])

    live = (
        [(ASSET_AGENT, i) for i, r in agents.items() if r["published_version"] is not None]
        + [(ASSET_SKILL, i) for i, r in skills.items() if r["published_version"] is not None]
        + [(ASSET_WORKFLOW, i) for i, r in workflows.items() if r["status"] == "live"]
    )
    with_cases = {(str(c["kind"]), str(c["asset_id"])) for c in cases if c["status"] == CASE_ACTIVE}
    return {
        "failingSuites": sum(1 for s in snap.suites if s["failing"]),
        "gatesBlocked": sum(1 for g in snap.gates if g["blocked"]),
        "liveUntested": sum(1 for kind, i in live if not passing(kind, i)),
        "notRun": sum(1 for key in with_cases if key not in latest_run),
    }
