"""Whether an agent's version may publish on its evals: one more rule in the publish gate, which the publish check, the
publish request, an approval and an eval run's reply all read. The rule itself is SQL in the store
(`store/assurance_list.version_gate`, the same one the Evals page's `gates` uses); this module reads the team's
evalsRequired setting, runs the rule for one version and words its steps and problems."""

from __future__ import annotations

from typing import TypedDict, cast

from ops_access import team_on
from ops_agents.domain.evals import ASSET_AGENT, DEFAULT_TIER, MODE_BLOCKING, STEP_FAIL, STEP_PENDING, step_mode
from ops_service_kit.http import Json, JsonList

from ..store.agent_registry import AgentRow
from ..store.assurance_list import Checks, VersionGate, version_gate
from ..store.tenancy import NoTenantError, tenant_tx
from .deps import Runtime
from .platform_policies import PolicyUnread

REQUIRED_KEY = "evalsRequired"
STEP_LABELS = {"structural": "Structure checks", "pass_rate": "Pass rate", "regressions": "Regressions"}
UNREAD = "The team's eval setting could not be read just now"


class GateStep(TypedDict):
    step: str
    label: str
    mode: str
    result: str
    detail: str


async def evals_required(rt: Runtime, team: str | None) -> bool | None:
    """Whether `team` turned evalsRequired on, read live from platform-service as publishReview is; None when it could
    not be read. Off with no platform configured or no tenant yet (the start-up seed)."""
    if team is None or rt.policies is None:
        return False
    try:
        return team_on(await rt.policies.value(REQUIRED_KEY), team)
    except NoTenantError:
        return False
    except PolicyUnread:
        return None


def checks_of(rt: Runtime, *, required: bool) -> Checks:
    """The default tier's blocking steps and the lowest pass rate, with the team's evalsRequired."""
    blocking = frozenset(step for step in STEP_LABELS if step_mode(DEFAULT_TIER, step) == MODE_BLOCKING)
    return Checks(tier=DEFAULT_TIER, blocking=blocking, min_pass_rate=rt.settings.eval_min_pass_rate, required=required)


def eval_steps(
    tier: str,
    minimum: float,
    version: int,
    *,
    passed: int,
    total: int,
    regressions: int,
    pass_rate_result: str,
    regressions_result: str,
) -> list[GateStep]:
    """The pass-rate and regression steps worded from the results the store's rule returned; nothing is decided here."""

    def step(name: str, result: str, detail: str) -> GateStep:
        return {
            "step": name,
            "label": STEP_LABELS[name],
            "mode": step_mode(tier, name),
            "result": result,
            "detail": detail,
        }

    if pass_rate_result == STEP_PENDING:
        pending = f"No saved cases have run on version {version}."
        return [step("pass_rate", STEP_PENDING, pending), step("regressions", STEP_PENDING, pending)]
    rate_failed = pass_rate_result == STEP_FAIL
    return [
        step(
            "pass_rate",
            pass_rate_result,
            f"{passed} of {total} cases pass" + (f"; at least {round(minimum * 100)}% must." if rate_failed else "."),
        ),
        step(
            "regressions",
            regressions_result,
            f"{regressions} cases pass on the live version and fail on this one."
            if regressions_result == STEP_FAIL
            else "No case that passes live fails here.",
        ),
    ]


def _steps(checks: Checks, version: int, g: VersionGate) -> list[GateStep]:
    return eval_steps(
        checks.tier,
        checks.min_pass_rate,
        version,
        passed=g.passed,
        total=g.total,
        regressions=g.regressions,
        pass_rate_result=g.pass_rate_result,
        regressions_result=g.regressions_result,
    )


def _problem(kind: str, message: str, steps: list[GateStep]) -> Json:
    return {"kind": kind, "message": message, "details": {"steps": cast(JsonList, steps)}}


async def gate(rt: Runtime, row: AgentRow, version: int) -> tuple[list[Json], list[GateStep]]:
    """The eval problems (`PublishBlocker` rows) that stop `version` of the agent from publishing, and its steps.
    Read in the acting team; an approval reads it in the agent's own team (`publish_reviews`). Without evalsRequired,
    no cases and no run add nothing; a setting that cannot be read refuses."""
    required = await evals_required(rt, row.team_id)
    if required is None:
        return [_problem("eval_setting_unread", f"{UNREAD}; try the publish again in a moment.", [])], []
    checks = checks_of(rt, required=required)
    async with tenant_tx(rt.db) as conn:
        found = await version_gate(conn, ASSET_AGENT, row.id, version, checks)
    steps = _steps(checks, version, found)
    if not found.blocked:
        return [], steps
    return [_problem(*_why(found, version, steps), steps)], steps


def _why(found: VersionGate, version: int, steps: list[GateStep]) -> tuple[str, str]:
    """The problem's kind and message for a blocked version: no cases or no run (only with evalsRequired), else the
    blocking steps that failed."""
    required = "The team requires evals to publish, and"
    if found.pass_rate_result == STEP_PENDING:
        if found.cases == 0:
            return "eval_no_cases", f"{required} this agent has no saved cases."
        return "eval_not_run", f"{required} no saved cases have run on version {version}."
    failed = [f"{s['label']}: {s['detail']}" for s in steps if s["result"] == STEP_FAIL and s["mode"] == MODE_BLOCKING]
    return "eval_failed", f"A blocking eval step failed on version {version}. " + " ".join(failed)


async def problems(rt: Runtime, row: AgentRow, version: int) -> list[Json]:
    """Only the problems of `gate`."""
    return (await gate(rt, row, version))[0]
