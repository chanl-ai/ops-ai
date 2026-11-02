"""Run a dataset of cases through one existing agent test turn each. No local runner."""

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
    EvalCase,
    EvalCheck,
    score_case,
    turn_from_test,
    unknown_check_types,
)
from ops_service_kit.errors import Unprocessable
from ops_service_kit.ids import new_id

TurnFn = Callable[[str, tuple[str, ...]], Awaitable[dict[str, Any]]]


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


async def run_eval(agent_id: str, cases: list[EvalCase], turn: TurnFn) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    passed = 0
    for case in cases:
        view = turn_from_test(await turn(case.input, case.collections))
        outcome = score_case(case, view)
        if outcome.status == CHECK_STATUS_PASS:
            passed += 1
        results.append(
            {
                "caseName": case.name,
                "draft": {
                    "status": outcome.status,
                    "reply": outcome.reply,
                    "checks": [{"label": item.label, "status": item.status} for item in outcome.checks],
                    "latencyMs": outcome.latency_ms,
                },
                "live": None,
                "regression": False,
            }
        )
    return {
        "id": new_id(EVAL_RUN_PREFIX),
        "agentId": agent_id,
        "status": EVAL_STATUS_COMPLETE,
        "summary": {"passed": passed, "total": len(cases), "regressions": 0},
        "results": results,
    }


def _mapping(item: Any) -> dict[str, Any]:
    return cast(dict[str, Any], item) if isinstance(item, dict) else {}


def _case(item: Any) -> EvalCase:
    data = _mapping(item)
    context = _mapping(data.get("context"))
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
    data = _mapping(item)
    tool = data.get("tool")
    text = data.get("text")
    return EvalCheck(
        type=str(data.get("type") or ""),
        tool=str(tool) if tool is not None else None,
        text=str(text) if text is not None else None,
    )
