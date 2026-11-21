"""Dataset-eval kinds and scoring. Check types are named constants; the string checks score deterministically, and a
judge check scores on the verdict it is given."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final, cast

from ops_service_kit.http import Json

CHECK_CALLS_TOOL: Final = "calls_tool"
CHECK_REPLY_CONTAINS: Final = "reply_contains"
CHECK_REFUSES: Final = "refuses"
# Scored by a model judge on its rubric (ops_agent_kernel.judge), the verdict awaited in app/evals.py.
CHECK_JUDGE: Final = "judge"
CHECK_TYPES: Final[frozenset[str]] = frozenset({CHECK_CALLS_TOOL, CHECK_REPLY_CONTAINS, CHECK_REFUSES, CHECK_JUDGE})

CHECK_STATUS_PASS: Final = "pass"
CHECK_STATUS_FAIL: Final = "fail"
EVAL_STATUS_COMPLETE: Final = "complete"
EVAL_RUN_PREFIX: Final = "evr"
CHECK_UNKNOWN_CODE: Final = "unknown_check_type"
CASES_EMPTY_CODE: Final = "empty_cases"
RUBRIC_REQUIRED_CODE: Final = "rubric_required"

# What a saved case set or a run belongs to. Workflows keep no cases: their runs are the structural test runs.
ASSET_AGENT: Final = "agent"
ASSET_SKILL: Final = "skill"
ASSET_WORKFLOW: Final = "workflow"
CASE_ASSET_KINDS: Final[frozenset[str]] = frozenset({ASSET_AGENT, ASSET_SKILL})
CASE_ACTIVE: Final = "active"
CASE_DRAFT: Final = "draft"
TRIGGER_MANUAL: Final = "manual"
TRIGGER_PUBLISH_REQUEST: Final = "publish_request"
# Until the model inventory holds a record, every asset is in this tier.
DEFAULT_TIER: Final = "medium"

STEP_PASS: Final = "pass"
STEP_FAIL: Final = "fail"
STEP_PENDING: Final = "pending"
MODE_BLOCKING: Final = "blocking"
MODE_ADVISORY: Final = "advisory"
# Which publish-check steps stop a publish at each risk tier; the rest need the approver's reason.
BLOCKING_STEPS: Final[dict[str, frozenset[str]]] = {
    "low": frozenset(),
    "medium": frozenset({"structural", "pass_rate"}),
    "high": frozenset({"structural", "pass_rate", "regressions"}),
}


def pass_rate(passed: int, total: int) -> float | None:
    return round(passed / total, 4) if total else None


def step_mode(tier: str, step: str) -> str:
    return MODE_BLOCKING if step in BLOCKING_STEPS.get(tier, BLOCKING_STEPS[DEFAULT_TIER]) else MODE_ADVISORY


@dataclass(frozen=True)
class EvalCheck:
    type: str
    tool: str | None = None
    text: str | None = None
    rubric: str | None = None


@dataclass(frozen=True)
class EvalCase:
    name: str
    input: str
    checks: tuple[EvalCheck, ...]
    collections: tuple[str, ...] = ()


@dataclass(frozen=True)
class TurnView:
    reply: str
    tool_names: tuple[str, ...]
    blocked_topic: str | None
    latency_ms: int


@dataclass(frozen=True)
class CheckResult:
    label: str
    status: str
    # The judge's one-line reason and its confidence (not asked for yet, so None); None for the string checks.
    reason: str | None = None
    confidence: float | None = None


@dataclass(frozen=True)
class Judged:
    """A judge's verdict on one check; `passed` None is a judge that did not answer, which scores as a fail."""

    passed: bool | None
    reason: str
    confidence: float | None = None


@dataclass(frozen=True)
class CaseOutcome:
    status: str
    reply: str
    checks: tuple[CheckResult, ...]
    latency_ms: int


def check_label(check: EvalCheck) -> str:
    if check.type == CHECK_CALLS_TOOL:
        return f"Calls {check.tool}" if check.tool else CHECK_CALLS_TOOL
    if check.type == CHECK_REPLY_CONTAINS:
        return f"Reply contains “{check.text}”" if check.text else CHECK_REPLY_CONTAINS
    if check.type == CHECK_REFUSES:
        return f"Refuses: {check.text}" if check.text else CHECK_REFUSES
    if check.type == CHECK_JUDGE:
        return f"Judge: {check.rubric}" if check.rubric else CHECK_JUDGE
    return check.type


def judge_evidence(turn: TurnView) -> str:
    """What the judge is shown of a turn: the reply and the tools it called, never the agent's instructions."""
    tools = ", ".join(turn.tool_names) or "none"
    return f"Reply:\n{turn.reply}\n\nTools called: {tools}"


def score_check(check: EvalCheck, turn: TurnView, judged: Judged | None = None) -> CheckResult:
    if check.type == CHECK_JUDGE:
        ok = judged is not None and judged.passed is True
        reason = judged.reason if judged is not None else "The judge did not run."
        confidence = judged.confidence if judged is not None else None
        return CheckResult(check_label(check), CHECK_STATUS_PASS if ok else CHECK_STATUS_FAIL, reason, confidence)
    if check.type == CHECK_CALLS_TOOL:
        ok = bool(check.tool) and check.tool in turn.tool_names
    elif check.type == CHECK_REPLY_CONTAINS:
        ok = _holds(turn.reply, check.text)
    elif check.type == CHECK_REFUSES:
        ok = _refused(turn, check.text)
    else:
        ok = False
    return CheckResult(label=check_label(check), status=CHECK_STATUS_PASS if ok else CHECK_STATUS_FAIL)


def score_case(case: EvalCase, turn: TurnView, judged: Mapping[int, Judged] | None = None) -> CaseOutcome:
    """`judged` holds the verdict for each judge check, by its index in `case.checks`."""
    verdicts = judged or {}
    checks = tuple(score_check(check, turn, verdicts.get(i)) for i, check in enumerate(case.checks))
    failed = any(item.status == CHECK_STATUS_FAIL for item in checks)
    return CaseOutcome(
        status=CHECK_STATUS_FAIL if failed else CHECK_STATUS_PASS,
        reply=turn.reply,
        checks=checks,
        latency_ms=turn.latency_ms,
    )


def rubric_missing(cases: list[EvalCase]) -> str | None:
    """The first case with a judge check that has no rubric, by name."""
    return next((c.name for c in cases for k in c.checks if k.type == CHECK_JUDGE and not k.rubric), None)


def unknown_check_types(cases: list[EvalCase]) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for case in cases:
        for check in case.checks:
            if check.type not in CHECK_TYPES and check.type not in seen:
                seen.add(check.type)
                found.append(check.type)
    return found


def _list_field(data: Json, *keys: str) -> list[Any]:
    for key in keys:
        value = data.get(key)
        if isinstance(value, list):
            return cast(list[Any], value)
    return []


def _map_field(data: Json, *keys: str) -> Json:
    for key in keys:
        value = data.get(key)
        if isinstance(value, dict):
            return cast(Json, value)
    return {}


def turn_from_test(data: Json) -> TurnView:
    """A test-turn dict as the scorer sees it: reply, tool names, blocked topic, latency."""
    names: list[str] = []
    for call in _list_field(data, "toolCalls", "tool_calls"):
        if isinstance(call, dict):
            row = cast(Json, call)
            name = str(row.get("name") or row.get("tool") or "")
            if name:
                names.append(name)
    blocked = _map_field(data, "blockedBy", "blocked_by")
    topic = str(blocked.get("topic") or "")
    raw_latency = data.get("tookMs") if data.get("tookMs") is not None else data.get("took_ms")
    return TurnView(
        reply=str(data.get("reply") or ""),
        tool_names=tuple(names),
        blocked_topic=topic or None,
        latency_ms=int(cast(int | float | str, raw_latency or 0)),
    )


def _holds(haystack: str, needle: str | None) -> bool:
    return bool(needle) and needle.lower() in haystack.lower()


def _refused(turn: TurnView, text: str | None) -> bool:
    if text:
        return _holds(turn.reply, text) or _holds(turn.blocked_topic or "", text)
    return turn.blocked_topic is not None
