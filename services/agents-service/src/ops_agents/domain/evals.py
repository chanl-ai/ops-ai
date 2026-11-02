"""Dataset-eval kinds and scoring. Check types are named constants; scoring is deterministic."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final, cast

CHECK_CALLS_TOOL: Final = "calls_tool"
CHECK_REPLY_CONTAINS: Final = "reply_contains"
CHECK_REFUSES: Final = "refuses"
CHECK_TYPES: Final[frozenset[str]] = frozenset({CHECK_CALLS_TOOL, CHECK_REPLY_CONTAINS, CHECK_REFUSES})

CHECK_STATUS_PASS: Final = "pass"
CHECK_STATUS_FAIL: Final = "fail"
EVAL_STATUS_COMPLETE: Final = "complete"
EVAL_RUN_PREFIX: Final = "evr"
CHECK_UNKNOWN_CODE: Final = "unknown_check_type"
CASES_EMPTY_CODE: Final = "empty_cases"


@dataclass(frozen=True)
class EvalCheck:
    type: str
    tool: str | None = None
    text: str | None = None


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
    return check.type


def score_check(check: EvalCheck, turn: TurnView) -> CheckResult:
    if check.type == CHECK_CALLS_TOOL:
        ok = bool(check.tool) and check.tool in turn.tool_names
    elif check.type == CHECK_REPLY_CONTAINS:
        ok = _holds(turn.reply, check.text)
    elif check.type == CHECK_REFUSES:
        ok = _refused(turn, check.text)
    else:
        ok = False
    return CheckResult(label=check_label(check), status=CHECK_STATUS_PASS if ok else CHECK_STATUS_FAIL)


def score_case(case: EvalCase, turn: TurnView) -> CaseOutcome:
    checks = tuple(score_check(check, turn) for check in case.checks)
    failed = any(item.status == CHECK_STATUS_FAIL for item in checks)
    return CaseOutcome(
        status=CHECK_STATUS_FAIL if failed else CHECK_STATUS_PASS,
        reply=turn.reply,
        checks=checks,
        latency_ms=turn.latency_ms,
    )


def unknown_check_types(cases: list[EvalCase]) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for case in cases:
        for check in case.checks:
            if check.type not in CHECK_TYPES and check.type not in seen:
                seen.add(check.type)
                found.append(check.type)
    return found


def _list_field(data: dict[str, Any], *keys: str) -> list[Any]:
    for key in keys:
        value = data.get(key)
        if isinstance(value, list):
            return cast(list[Any], value)
    return []


def _map_field(data: dict[str, Any], *keys: str) -> dict[str, Any]:
    for key in keys:
        value = data.get(key)
        if isinstance(value, dict):
            return cast(dict[str, Any], value)
    return {}


def turn_from_test(data: dict[str, Any]) -> TurnView:
    """A test-turn dict as the scorer sees it: reply, tool names, blocked topic, latency."""
    names: list[str] = []
    for call in _list_field(data, "toolCalls", "tool_calls"):
        if isinstance(call, dict):
            row = cast(dict[str, Any], call)
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
        latency_ms=int(raw_latency or 0),
    )


def _holds(haystack: str, needle: str | None) -> bool:
    return bool(needle) and needle.lower() in haystack.lower()


def _refused(turn: TurnView, text: str | None) -> bool:
    if text:
        return _holds(turn.reply, text) or _holds(turn.blocked_topic or "", text)
    return turn.blocked_topic is not None
