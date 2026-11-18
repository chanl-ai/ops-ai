"""The Evals lists (`GET /v1/assurance/suites|runs|gates`) a page at a time in SQL: each list is one select over the
acting team's agents, skills and workflows (`assets`), their saved cases and runs (`store/evals.py`), the workflows'
test runs (`registry_validations`) and the publish requests, so the search, the filters, the facets, the total, the
sort and the page come from the database, and only the page's rows are read further (`suite_details`). `stats` reads
the page's figures and each tab's count in one statement. Every branch names its tenant and team in the query as well
as by the row policies."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, cast

import sqlalchemy as sa
from pydantic import BaseModel, JsonValue
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from ops_service_kit.listing import ListParams
from ops_store.dialect import json_text
from ops_store.listing import ListPage, list_page
from ops_store.team_scope import team_visible

from .agent_registry import publish_requests, registry_agent_versions, registry_agents
from .evals import eval_cases, eval_runs
from .graphs import mine
from .skills import registry_skill_versions, registry_skills
from .tenancy import current_tenant, tenant_tx
from .workflow_registry import registry_validations, registry_workflows

# The values stored in eval_cases, eval_runs and registry_publish_requests (store/evals.py writes them).
ASSET_AGENT, ASSET_SKILL, ASSET_WORKFLOW = "agent", "skill", "workflow"
CASE_ACTIVE, CASE_DRAFT = "active", "draft"
TRIGGER_MANUAL = "manual"
DECIDED = ("approved", "rejected", "returned")
OPEN = "pending"


@dataclass(frozen=True)
class Checks:
    """How the caller judges a publish: the tier every list shows, the steps that block at it, the lowest pass rate."""

    tier: str
    blocking: frozenset[str]
    min_pass_rate: float


def _text(value: str) -> sa.ColumnElement[str]:
    # A constant of this module, written into the SQL so a union and a GROUP BY carry no bound value.
    return sa.literal_column(f"'{value}'", sa.String())


def _no_int() -> sa.ColumnElement[int]:
    return sa.cast(sa.null(), sa.Integer())


def assets() -> sa.Subquery:
    """The agents, skills and workflows the acting team sees, one row each: kind, id, team, the name the page shows
    (the current version's, else the slug), the published version and whether it is live (1 or 0)."""
    a, av, s, sv, w = (
        registry_agents,
        registry_agent_versions,
        registry_skills,
        registry_skill_versions,
        registry_workflows,
    )
    agent_version = sa.and_(
        av.c.tenant_id == a.c.tenant_id, av.c.agent_id == a.c.id, av.c.version == a.c.version, team_visible(av)
    )
    agents = (
        sa.select(
            _text(ASSET_AGENT).label("kind"),
            a.c.id.label("asset_id"),
            a.c.team_id.label("team_id"),
            sa.func.coalesce(json_text(av.c.spec, "name"), a.c.slug).label("name"),
            a.c.published_version.label("published_version"),
            sa.case((a.c.published_version.is_not(None), 1), else_=0).label("live"),
        )
        .select_from(a.outerjoin(av, agent_version))
        .where(mine(a), team_visible(a))
    )
    skill_version = sa.and_(
        sv.c.tenant_id == s.c.tenant_id, sv.c.skill_id == s.c.id, sv.c.version == s.c.version, team_visible(sv)
    )
    skills = (
        sa.select(
            _text(ASSET_SKILL),
            s.c.id,
            s.c.team_id,
            sa.func.coalesce(json_text(sv.c.content, "name"), s.c.slug),
            s.c.published_version,
            sa.case((s.c.published_version.is_not(None), 1), else_=0),
        )
        .select_from(s.outerjoin(sv, skill_version))
        .where(mine(s), team_visible(s))
    )
    workflows = sa.select(
        _text(ASSET_WORKFLOW),
        w.c.id,
        w.c.team_id,
        w.c.name,
        w.c.published_version,
        sa.case((w.c.status == "live", 1), else_=0),
    ).where(mine(w), team_visible(w), w.c.status != "deleted")
    return sa.union_all(agents, skills, workflows).subquery("assets")


def _latest(rank_by: Sequence[sa.ColumnElement[Any]], name: str) -> sa.Subquery:
    """The newest of the team's saved-case runs per `rank_by`."""
    r = eval_runs
    n = sa.func.row_number().over(partition_by=list(rank_by), order_by=(r.c.ran_at.desc(), r.c.id.desc()))
    ranked = sa.select(r, n.label("n")).where(mine(r), team_visible(r)).subquery(f"{name}_ranked")
    return sa.select(ranked).where(ranked.c.n == 1).subquery(name)


def _latest_validation(name: str) -> sa.Subquery:
    """The newest test run of each workflow of the tenant; the team comes from the workflow it is joined to."""
    v = registry_validations
    n = sa.func.row_number().over(partition_by=v.c.workflow_id, order_by=(v.c.ran_at.desc(), v.c.id.desc()))
    ranked = sa.select(v, n.label("n")).where(mine(v)).subquery(f"{name}_ranked")
    return sa.select(ranked).where(ranked.c.n == 1).subquery(name)


def _result(run_id: sa.ColumnElement[Any], passed: sa.ColumnElement[int], total: sa.ColumnElement[int]) -> Any:
    return sa.case(
        (sa.or_(run_id.is_(None), total == 0), _text("not_run")),
        (passed < total, _text("failing")),
        else_=_text("passing"),
    )


def suites(tier: str) -> sa.Subquery:
    """One row per agent or skill with saved cases or a run, and per workflow with a test run: its newest run's counts
    and `result` (not_run, failing, passing), its active and draft case counts."""
    u, c = assets(), eval_cases
    run = _latest((eval_runs.c.kind, eval_runs.c.asset_id), "latest_run")
    counts = (
        sa.select(
            c.c.kind,
            c.c.asset_id,
            sa.func.sum(sa.case((c.c.status == CASE_ACTIVE, 1), else_=0)).label("active"),
            sa.func.sum(sa.case((c.c.status == CASE_DRAFT, 1), else_=0)).label("drafts"),
        )
        .where(mine(c), team_visible(c))
        .group_by(c.c.kind, c.c.asset_id)
        .subquery("case_counts")
    )
    tested = (
        sa.select(
            u.c.kind,
            u.c.asset_id,
            u.c.name,
            u.c.team_id,
            _text(tier).label("tier"),
            run.c.id.label("run_id"),
            run.c.version.label("version"),
            run.c.live_version.label("live_version"),
            run.c.passed.label("passed"),
            run.c.total.label("total"),
            run.c.live_passed.label("live_passed"),
            run.c.regressions.label("regressions"),
            run.c.ran_at.label("ran_at"),
            sa.func.coalesce(counts.c.active, 0).label("cases"),
            sa.func.coalesce(counts.c.drafts, 0).label("draft_cases"),
            _result(run.c.id, run.c.passed, run.c.total).label("result"),
        )
        .select_from(
            u.outerjoin(run, sa.and_(run.c.kind == u.c.kind, run.c.asset_id == u.c.asset_id)).outerjoin(
                counts, sa.and_(counts.c.kind == u.c.kind, counts.c.asset_id == u.c.asset_id)
            )
        )
        .where(u.c.kind != ASSET_WORKFLOW, sa.or_(run.c.id.is_not(None), counts.c.kind.is_not(None)))
    )
    w, val = registry_workflows, _latest_validation("latest_validation")
    validated = (
        sa.select(
            _text(ASSET_WORKFLOW),
            w.c.id,
            w.c.name,
            w.c.team_id,
            _text(tier),
            val.c.id,
            w.c.published_version,
            w.c.published_version,
            val.c.passed,
            val.c.total,
            _no_int(),
            val.c.regressions,
            val.c.ran_at,
            val.c.total,
            sa.literal_column("0", sa.Integer()),
            _result(val.c.id, val.c.passed, val.c.total),
        )
        .select_from(w.join(val, sa.and_(val.c.tenant_id == w.c.tenant_id, val.c.workflow_id == w.c.id)))
        .where(mine(w), team_visible(w), w.c.status != "deleted")
    )
    return sa.union_all(tested, validated).subquery("suites")


def runs() -> sa.Subquery:
    """Every saved-case run of the team's agents and skills and every test run of its workflows, with its asset."""
    u, r = assets(), eval_runs
    saved = (
        sa.select(
            r.c.id.label("id"),
            r.c.kind.label("kind"),
            r.c.asset_id.label("asset_id"),
            u.c.name.label("name"),
            r.c.version.label("version"),
            r.c.trigger.label("trigger"),
            r.c.passed.label("passed"),
            r.c.total.label("total"),
            r.c.regressions.label("regressions"),
            r.c.duration_ms.label("duration_ms"),
            r.c.cost_usd.label("cost_usd"),
            r.c.ran_at.label("ran_at"),
        )
        .select_from(r.join(u, sa.and_(u.c.kind == r.c.kind, u.c.asset_id == r.c.asset_id)))
        .where(mine(r), team_visible(r), r.c.kind != ASSET_WORKFLOW)
    )
    w, v = registry_workflows, registry_validations
    tested = (
        sa.select(
            v.c.id,
            _text(ASSET_WORKFLOW),
            w.c.id,
            w.c.name,
            sa.func.coalesce(w.c.published_version, 0),
            _text(TRIGGER_MANUAL),
            v.c.passed,
            v.c.total,
            v.c.regressions,
            sa.literal_column("0", sa.Integer()),
            sa.cast(sa.literal_column("0"), sa.Float()),
            v.c.ran_at,
        )
        .select_from(v.join(w, sa.and_(w.c.tenant_id == v.c.tenant_id, w.c.id == v.c.workflow_id)))
        .where(mine(v), mine(w), team_visible(w), w.c.status != "deleted")
    )
    return sa.union_all(saved, tested).subquery("runs")


def gates(checks: Checks) -> sa.Subquery:
    """The publish requests of the team's agents, skills and workflows with the counts their checks read: an agent's or
    skill's newest run of the requested version, a workflow's newest test run. `blocked` is 1 when the request is
    open and a step that blocks at its tier fails (`checks.blocking`); `result` is blocked, ready or decided."""
    p, u, tier = publish_requests, assets(), checks.tier
    run = _latest((eval_runs.c.kind, eval_runs.c.asset_id, eval_runs.c.version), "version_run")
    val = _latest_validation("gate_validation")
    is_workflow = p.c.kind == ASSET_WORKFLOW
    joined = (
        p.join(u, sa.and_(u.c.kind == p.c.kind, u.c.asset_id == p.c.subject_id))
        .outerjoin(
            run,
            sa.and_(
                ~is_workflow, run.c.kind == p.c.kind, run.c.asset_id == p.c.subject_id, run.c.version == p.c.version
            ),
        )
        .outerjoin(val, sa.and_(is_workflow, val.c.workflow_id == p.c.subject_id))
    )
    summary_id = sa.func.coalesce(val.c.id, run.c.id)
    passed = sa.func.coalesce(val.c.passed, run.c.passed, 0)
    total = sa.func.coalesce(val.c.total, run.c.total, 0)
    regressions = sa.func.coalesce(val.c.regressions, run.c.regressions, 0)
    counted = sa.and_(summary_id.is_not(None), total > 0)
    failing: list[sa.ColumnElement[bool]] = []
    if "structural" in checks.blocking:
        failing.append(sa.and_(is_workflow, val.c.id.is_not(None), val.c.checks_failing > 0))
    if "pass_rate" in checks.blocking:
        rate = sa.cast(passed, sa.Float()) / sa.case((total > 0, total), else_=1)
        failing.append(sa.and_(counted, rate < sa.literal(checks.min_pass_rate, sa.Float())))
    if "regressions" in checks.blocking:
        failing.append(sa.and_(counted, regressions > 0))
    blocked = sa.and_(p.c.status == OPEN, sa.or_(*failing)) if failing else sa.false()
    q = sa.select(
        p.c.id.label("id"),
        p.c.kind.label("kind"),
        p.c.subject_id.label("asset_id"),
        u.c.name.label("name"),
        u.c.published_version.label("published_version"),
        p.c.version.label("version"),
        p.c.status.label("status"),
        p.c.requested_by.label("requested_by"),
        p.c.created_at.label("created_at"),
        _text(tier).label("tier"),
        summary_id.label("summary_id"),
        passed.label("passed"),
        total.label("total"),
        regressions.label("regressions"),
        val.c.checks_failing.label("checks_failing"),
        sa.case((blocked, 1), else_=0).label("blocked"),
        sa.case((blocked, _text("blocked")), (p.c.status.in_(DECIDED), _text("decided")), else_=_text("ready")).label(
            "result"
        ),
    )
    return q.select_from(joined).where(p.c.tenant_id == current_tenant()).subquery("gates")


async def suites_page(conn: AsyncConnection, params: ListParams, *, tier: str) -> ListPage:
    """Suites by name then kind and id; search over the asset's name; `kind`, `tier`, `result` filter and count."""
    u = suites(tier)
    return await list_page(
        conn,
        sa.select(u),
        params,
        search=[u.c.name],
        default_sort=sa.func.lower(u.c.name),
        filters={"kind": u.c.kind, "tier": u.c.tier, "result": u.c.result},
        facets={"kind": u.c.kind, "tier": u.c.tier, "result": u.c.result},
        key=(u.c.kind, u.c.asset_id),
    )


async def runs_page(conn: AsyncConnection, params: ListParams) -> ListPage:
    """Runs newest first, then by id; search over the asset's name; `kind` and `trigger` filter and count."""
    u = runs()
    return await list_page(
        conn,
        sa.select(u),
        params,
        search=[u.c.name],
        default_sort=u.c.ran_at.desc(),
        filters={"kind": u.c.kind, "trigger": u.c.trigger},
        facets={"kind": u.c.kind, "trigger": u.c.trigger},
        key=(u.c.id,),
    )


async def gates_page(conn: AsyncConnection, params: ListParams, *, checks: Checks) -> ListPage:
    """Publish checks newest request first, then by id; search over the asset's name; `tier`, `result` filter."""
    u = gates(checks)
    return await list_page(
        conn,
        sa.select(u),
        params,
        search=[u.c.name],
        default_sort=u.c.created_at.desc(),
        filters={"tier": u.c.tier, "result": u.c.result},
        facets={"tier": u.c.tier, "result": u.c.result},
        key=(u.c.id,),
    )


class Stats(BaseModel):
    """The Evals page's figures and each tab's row count, unfiltered."""

    failing_suites: int
    gates_blocked: int
    live_untested: int
    not_run: int
    suites: int
    runs: int
    gates: int


async def stats(conn: AsyncConnection, *, checks: Checks) -> Stats:
    """In one statement: failing suites, blocked publish checks, live assets whose newest run does not pass every case,
    assets with active cases and no run, and each tab's count."""
    s, r, g, u, c, e = suites(checks.tier), runs(), gates(checks), assets(), eval_cases, eval_runs

    def count(table: sa.FromClause, *where: sa.ColumnElement[bool]) -> Any:
        return sa.select(sa.func.count()).select_from(table).where(*where).scalar_subquery()

    run = _latest((e.c.kind, e.c.asset_id), "stats_run")
    val = _latest_validation("stats_validation")
    is_workflow = u.c.kind == ASSET_WORKFLOW
    newest = u.outerjoin(run, sa.and_(~is_workflow, run.c.kind == u.c.kind, run.c.asset_id == u.c.asset_id)).outerjoin(
        val, sa.and_(is_workflow, val.c.workflow_id == u.c.asset_id)
    )
    passed, total = sa.func.coalesce(val.c.passed, run.c.passed, 0), sa.func.coalesce(val.c.total, run.c.total, 0)
    passing = sa.and_(total > 0, passed == total)
    ran = sa.select(e.c.id).where(mine(e), team_visible(e), e.c.kind == c.c.kind, e.c.asset_id == c.c.asset_id)
    waiting = (
        sa.select(c.c.kind, c.c.asset_id)
        .where(mine(c), team_visible(c), c.c.status == CASE_ACTIVE, ~ran.exists())
        .distinct()
        .subquery("not_run")
    )
    q = sa.select(
        count(s, s.c.result == "failing").label("failing_suites"),
        count(g, g.c.blocked == 1).label("gates_blocked"),
        count(newest, u.c.live == 1, ~passing).label("live_untested"),
        count(waiting).label("not_run"),
        count(s).label("suites"),
        count(r).label("runs"),
        count(g).label("gates"),
    )
    row = (await conn.execute(q)).mappings().one()
    return Stats.model_validate(dict(row))


class CaseBody(BaseModel):
    """The part of a saved case's body a list shows."""

    input: str = ""


class Draft(BaseModel):
    """A draft case a review proposed, waiting for its owner."""

    id: str
    name: str
    # The case's input, from the body as the person wrote it.
    input: str
    review_id: str | None
    reason: str
    created_by: str
    created_at: str


class SuiteExtra(BaseModel):
    """What a suite row shows beyond the list's columns: its newest run's case results and its draft cases."""

    results: list[JsonValue] = []
    drafts: list[Draft] = []


async def suite_details(
    conn: AsyncConnection, rows: Sequence[tuple[str, str, str | None]]
) -> dict[tuple[str, str], SuiteExtra]:
    """The case results of each (kind, asset id, newest run id) row's run and its draft cases, by (kind, asset id),
    in three statements whatever the page size."""
    out = {(kind, asset_id): SuiteExtra() for kind, asset_id, _ in rows}
    saved = [run for kind, _, run in rows if run and kind != ASSET_WORKFLOW]
    tested = [run for kind, _, run in rows if run and kind == ASSET_WORKFLOW]
    e, v, c = eval_runs, registry_validations, eval_cases
    found = await conn.execute(
        sa.select(e.c.kind, e.c.asset_id, e.c.results).where(mine(e), team_visible(e), e.c.id.in_(saved))
    )
    for kind, asset_id, results in found:
        out[str(kind), str(asset_id)].results = list(results or [])
    found = await conn.execute(sa.select(v.c.workflow_id, v.c.results).where(mine(v), v.c.id.in_(tested)))
    for workflow_id, results in found:
        out[ASSET_WORKFLOW, str(workflow_id)].results = list(results or [])
    asked = sorted({asset_id for kind, asset_id, _ in rows if kind != ASSET_WORKFLOW})
    drafts = (
        sa.select(c)
        .where(mine(c), team_visible(c), c.c.status == CASE_DRAFT, c.c.asset_id.in_(asked))
        .order_by(c.c.kind, c.c.asset_id, c.c.position, c.c.id)
    )
    for d in (await conn.execute(drafts)).mappings():
        key = (str(d["kind"]), str(d["asset_id"]))
        if key in out:
            written = CaseBody.model_validate(d["body"] if isinstance(d["body"], dict) else {})
            out[key].drafts.append(Draft.model_validate({**d, "input": written.input}))
    return out


class Listed(BaseModel):
    """One Evals list's page, its suite extras (suites only) and the page's figures, read in one transaction."""

    page: dict[str, JsonValue]
    extras: dict[str, SuiteExtra] = {}
    stats: Stats


def _key(kind: str, asset_id: str) -> str:
    return f"{kind}:{asset_id}"


async def read_list(engine: AsyncEngine, tab: str, params: ListParams, checks: Checks) -> Listed:
    """`tab` (suites, runs or gates) a page at a time, its suite extras by "kind:asset id", and the figures."""
    async with tenant_tx(engine) as c:
        extras: dict[str, SuiteExtra] = {}
        if tab == "suites":
            listed = await suites_page(c, params, tier=checks.tier)
            keys = [(str(r["kind"]), str(r["asset_id"]), r["run_id"] and str(r["run_id"])) for r in listed["data"]]
            extras = {_key(*k): v for k, v in (await suite_details(c, keys)).items()}
        elif tab == "runs":
            listed = await runs_page(c, params)
        else:
            listed = await gates_page(c, params, checks=checks)
        figures = await stats(c, checks=checks)
    return Listed(page=cast(dict[str, JsonValue], listed), extras=extras, stats=figures)


__all__ = [
    "Checks",
    "Draft",
    "Listed",
    "Stats",
    "SuiteExtra",
    "assets",
    "gates",
    "gates_page",
    "read_list",
    "runs",
    "runs_page",
    "stats",
    "suite_details",
    "suites",
    "suites_page",
]
