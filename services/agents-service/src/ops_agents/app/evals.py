"""Run a dataset of cases through one existing agent test turn each. No local runner. A kept run starts in
`api/eval_runs.py` (`run_saved`) and is answered as `stored_run` shapes it."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, cast

from ops_agents.domain.evals import (
    CASES_EMPTY_CODE,
    CHECK_STATUS_PASS,
    CHECK_TYPES,
    CHECK_UNKNOWN_CODE,
    EVAL_RUN_PREFIX,
    EVAL_STATUS_COMPLETE,
    CaseOutcome,
    EvalCase,
    EvalCheck,
    score_case,
    turn_from_test,
    unknown_check_types,
)
from ops_service_kit.errors import Unprocessable
from ops_service_kit.http import Json, JsonList
from ops_service_kit.ids import new_id
from ops_service_kit.narrow import json_object

TurnFn = Callable[[str, tuple[str, ...]], Awaitable[Json]]


def parse_cases(raw: list[Any]) -> list[EvalCase]:
    if not raw:
        raise Unprocessable("cases must not be empty.", code=CASES_EMPTY_CODE)
    cases = [_case(item) for item in raw]
    unknown = unknown_check_types(cases)
    if unknown:
        raise Unprocessable(
            f"Unknown check type: {unknown[0]}. Allowed: {', '.join(sorted(CHECK_TYPES))}.",
            code=CHECK_UNKNOWN_CODE,
            details={"type": unknown[0]},
        )
    return cases


def _outcome(outcome: CaseOutcome) -> Json:
    return {
        "status": outcome.status,
        "reply": outcome.reply,
        "checks": [{"label": item.label, "status": item.status} for item in outcome.checks],
        "latencyMs": outcome.latency_ms,
    }


async def run_eval(agent_id: str, cases: list[EvalCase], turn: TurnFn, live_turn: TurnFn | None = None) -> Json:
    """Scores each case on the version `turn` runs; with `live_turn`, on the live version too, and a case that passes
    live but fails now is a regression."""
    results: JsonList = []
    passed = regressions = 0
    for case in cases:
        outcome = score_case(case, turn_from_test(await turn(case.input, case.collections)))
        live = None
        if live_turn is not None:
            live = score_case(case, turn_from_test(await live_turn(case.input, case.collections)))
        regression = live is not None and live.status == CHECK_STATUS_PASS and outcome.status != CHECK_STATUS_PASS
        passed += outcome.status == CHECK_STATUS_PASS
        regressions += regression
        results.append(
            {
                "caseName": case.name,
                "draft": _outcome(outcome),
                "live": _outcome(live) if live is not None else None,
                "regression": regression,
            }
        )
    return {
        "id": new_id(EVAL_RUN_PREFIX),
        "agentId": agent_id,
        "status": EVAL_STATUS_COMPLETE,
        "summary": {"passed": passed, "total": len(cases), "regressions": regressions},
        "results": results,
    }


def stored_run(row: Json) -> Json:
    """A kept run as the API answers it (`EvalRunRecord`): the start of a run, each row of an agent's runs and the
    read of one."""
    return {
        "id": row["id"],
        "agentId": row["asset_id"],
        "version": row["version"],
        "liveVersion": row["live_version"],
        "trigger": row["trigger"],
        "status": EVAL_STATUS_COMPLETE,
        "summary": {"passed": row["passed"], "total": row["total"], "regressions": row["regressions"]},
        "results": row["results"],
        "costUsd": row["cost_usd"],
        "startedBy": row["started_by"],
        "ranAt": row["ran_at"],
    }


def _case(item: Any) -> EvalCase:
    data = json_object(item)
    context = json_object(data.get("context"))
    raw_collections = context.get("collections")
    collections = cast(list[Any], raw_collections) if isinstance(raw_collections, list) else []
    raw_checks = data.get("checks")
    checks = tuple(_check(row) for row in cast(list[Any], raw_checks)) if isinstance(raw_checks, list) else ()
    return EvalCase(
        name=str(data.get("name") or ""),
        input=str(data.get("input") or ""),
        checks=checks,
        collections=tuple(str(value) for value in collections),
    )


def _check(item: Any) -> EvalCheck:
    data = json_object(item)
    tool = data.get("tool")
    text = data.get("text")
    return EvalCheck(
        type=str(data.get("type") or ""),
        tool=str(tool) if tool is not None else None,
        text=str(text) if text is not None else None,
    )
