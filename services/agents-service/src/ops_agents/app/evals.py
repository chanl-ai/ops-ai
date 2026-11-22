"""Run a dataset of cases through one existing agent test turn each. No local runner. A kept run starts in
`api/eval_runs.py` (`run_saved`) and is answered as `stored_run` shapes it."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from decimal import Decimal
from typing import Any, cast

from ops_agent_kernel.judge import Verdict
from ops_agents.domain.evals import (
    CASES_EMPTY_CODE,
    CHECK_JUDGE,
    CHECK_STATUS_PASS,
    CHECK_TYPES,
    CHECK_UNKNOWN_CODE,
    EVAL_RUN_PREFIX,
    EVAL_STATUS_COMPLETE,
    RUBRIC_REQUIRED_CODE,
    CaseOutcome,
    CheckResult,
    EvalCase,
    EvalCheck,
    Judged,
    judge_evidence,
    rubric_missing,
    score_case,
    turn_from_test,
    unknown_check_types,
)
from ops_metering import PriceTable, Usage, cost
from ops_service_kit.errors import Unprocessable
from ops_service_kit.http import Json, JsonList
from ops_service_kit.ids import new_id
from ops_service_kit.narrow import field, json_list, json_object

# One test turn: the reply dict `one_test_turn` answers, its `usage` naming the alias the turn ran on.
TurnFn = Callable[[str, tuple[str, ...]], Awaitable[Json]]
# One judge call on (rubric, evidence, the turn's alias): its verdict and the alias it was spent on.
JudgeFn = Callable[[str, str, str], Awaitable[tuple[Verdict, str]]]


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
    if (named := rubric_missing(cases)) is not None:
        raise Unprocessable(
            f"A judge check needs a rubric (case {named}).", code=RUBRIC_REQUIRED_CODE, details={"case": named}
        )
    return cases


def _check_result(item: CheckResult) -> Json:
    out: Json = {"label": item.label, "status": item.status}
    if item.reason is not None:  # a judge check
        out |= {"reason": item.reason, "confidence": item.confidence}
    return out


def _outcome(outcome: CaseOutcome) -> Json:
    return {
        "status": outcome.status,
        "reply": outcome.reply,
        "checks": [_check_result(item) for item in outcome.checks],
        "latencyMs": outcome.latency_ms,
    }


class _Spend:
    """Tokens a run spent, per alias, priced once at the end."""

    def __init__(self) -> None:
        self.by_alias: dict[str, Usage] = {}

    def add(self, alias: str, input_tokens: int, output_tokens: int, calls: int) -> None:
        was = self.by_alias.get(alias, Usage(calls=0))
        self.by_alias[alias] = Usage(
            was.input_tokens + input_tokens, was.output_tokens + output_tokens, was.calls + calls
        )

    def merge(self, other: _Spend) -> None:
        for alias, u in other.by_alias.items():
            self.add(alias, u.input_tokens, u.output_tokens, u.calls)

    def priced(self, prices: PriceTable) -> tuple[float, bool]:
        """The cost in the price table's currency, and whether an alias that used tokens has no price there (its
        tokens count as 0, so the cost is a floor, never a silent 0)."""
        total = sum((cost(u, prices.price(a)) for a, u in self.by_alias.items()), Decimal(0))
        unpriced = any(u.tokens and not prices.priced(a) for a, u in self.by_alias.items())
        return float(total), unpriced


async def _scored(case: EvalCase, data: Json, judge: JudgeFn | None, spend: _Spend, judging: _Spend) -> CaseOutcome:
    """One turn scored: its usage counted in `spend`, and each judge check judged on the turn's reply, the judge's
    usage counted in `spend` and in `judging` too."""
    usage = json_object(data.get("usage"))
    alias = str(usage.get("model") or data.get("model") or "")
    spend.add(alias, field(usage, "inputTokens", int, 0), field(usage, "outputTokens", int, 0), 1)
    view = turn_from_test(data)
    judged: dict[int, Judged] = {}
    for i, check in enumerate(case.checks):
        if check.type != CHECK_JUDGE:
            continue
        if judge is None:
            judged[i] = Judged(None, "No judge is configured.")
            continue
        verdict, spent_on = await judge(check.rubric or "", judge_evidence(view), alias)
        used = (verdict.usage.input_tokens, verdict.usage.output_tokens, verdict.usage.requests)
        spend.add(spent_on, *used)
        judging.add(spent_on, *used)
        judged[i] = Judged(verdict.passed, verdict.reason, verdict.confidence)
    return score_case(case, view, judged)


async def run_eval(
    agent_id: str,
    cases: list[EvalCase],
    turn: TurnFn,
    live_turn: TurnFn | None = None,
    *,
    judge: JudgeFn | None = None,
    prices: PriceTable | None = None,
) -> Json:
    """Scores each case on the version `turn` runs; with `live_turn`, on the live version too, and a case that passes
    live but fails now is a regression. `costUsd` is every turn's and judge call's tokens priced by alias; `unpriced`
    says an alias that spent tokens has no price."""
    results: JsonList = []
    passed = regressions = 0
    table = prices or PriceTable()
    spend = _Spend()
    for case in cases:
        mine, judging = _Spend(), _Spend()
        outcome = await _scored(case, await turn(case.input, case.collections), judge, mine, judging)
        live = None
        if live_turn is not None:
            live = await _scored(case, await live_turn(case.input, case.collections), judge, mine, judging)
        spend.merge(mine)
        regression = live is not None and live.status == CHECK_STATUS_PASS and outcome.status != CHECK_STATUS_PASS
        passed += outcome.status == CHECK_STATUS_PASS
        regressions += regression
        results.append(
            {
                "caseName": case.name,
                "draft": _outcome(outcome),
                "live": _outcome(live) if live is not None else None,
                "regression": regression,
                # Kept on each case, as a run stores its results whole: the run's own flag is read from them.
                "unpriced": mine.priced(table)[1],
                # The part of that the judge spent: only a case with a judge check can hold it.
                "judgeUnpriced": judging.priced(table)[1],
            }
        )
    cost_usd, unpriced = spend.priced(table)
    return {
        "id": new_id(EVAL_RUN_PREFIX),
        "agentId": agent_id,
        "status": EVAL_STATUS_COMPLETE,
        "summary": {"passed": passed, "total": len(cases), "regressions": regressions},
        "results": results,
        "costUsd": cost_usd,
        "unpriced": unpriced,
    }


def stored_run(row: Json, *, results: bool = True) -> Json:
    """A kept run as the API answers it: the start of a run and the read of one (`EvalRunRecord`), or with
    `results=False` a row of an agent's runs list (`EvalRunRow`), which leaves the case results out."""
    shaped: Json = {
        "id": row["id"],
        "agentId": row["asset_id"],
        "version": row["version"],
        "liveVersion": row["live_version"],
        "trigger": row["trigger"],
        "status": EVAL_STATUS_COMPLETE,
        "summary": {"passed": row["passed"], "total": row["total"], "regressions": row["regressions"]},
        "costUsd": row["cost_usd"],
        "unpriced": any(json_object(r).get("unpriced") is True for r in json_list(row["results"])),
        "startedBy": row["started_by"],
        "ranAt": row["ran_at"],
    }
    return {**shaped, "results": row["results"]} if results else shaped


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
    rubric = data.get("rubric")
    return EvalCheck(
        type=str(data.get("type") or ""),
        tool=str(tool) if tool is not None else None,
        text=str(text) if text is not None else None,
        rubric=str(rubric) if rubric is not None else None,
    )
