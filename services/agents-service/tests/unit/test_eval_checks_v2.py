"""The eval checks for the new behaviour, by the failure modes of docs/design/agents-v2/evals.md's acceptance table:
`mode: [direct]` passing on a turn that planned (row 4), a judge asked about a case that already failed (row 5), and a
write in an eval that is not seen as paused (row 3); plus the typed-answer, cost and not-called checks the page adds."""

from __future__ import annotations

from typing import Any, cast

from ops_agent_kernel.judge import Verdict
from ops_agent_kernel.types import TokenUsage
from ops_agents.app.evals import parse_cases, run_eval
from ops_agents.domain.evals import EvalCase, EvalCheck, TurnView, score_case, turn_from_test
from ops_service_kit.http import Json


def _turn(**over: Any) -> TurnView:
    return TurnView(reply="Held W-88213.", tool_names=(), blocked_topic=None, latency_ms=10, **over)


def _status(check: EvalCheck, turn: TurnView) -> str:
    return score_case(EvalCase("c", "m", (check,)), turn).status


def test_direct_mode_fails_a_turn_that_planned() -> None:
    direct = EvalCheck("mode_in", modes=("direct",))
    assert _status(direct, _turn(modes=("direct",))) == "pass"
    assert _status(direct, _turn(modes=("plan",))) == "fail"
    assert _status(EvalCheck("mode_in", modes=("direct", "plan")), _turn(modes=("plan",))) == "pass"


async def test_a_judge_is_not_asked_about_a_case_that_already_failed() -> None:
    asked: list[str] = []

    async def judge(rubric: str, evidence: str, alias: str) -> tuple[Verdict, str]:
        asked.append(rubric)
        return Verdict(True, "fine", TokenUsage()), alias

    async def turn(message: str, collections: tuple[str, ...]) -> Json:
        return {"reply": "No idea.", "toolCalls": [], "usage": {"model": "m"}}

    cases = parse_cases(
        [
            {
                "name": "fails",
                "input": "x",
                "checks": [{"type": "reply_contains", "text": "hold"}, {"type": "judge", "rubric": "polite"}],
            },
            {"name": "judged", "input": "y", "checks": [{"type": "judge", "rubric": "kind"}]},
        ]
    )
    run = await run_eval("ag", cases, turn, judge=judge)
    assert asked == ["kind"], asked
    results = cast(list[dict[str, Any]], run["results"])
    assert [r["draft"]["status"] for r in results] == ["fail", "pass"]


def test_a_write_in_an_eval_is_seen_paused_and_not_sent() -> None:
    data: Json = {
        "reply": "This needs approval.",
        "toolCalls": [{"name": "place_wire_hold", "status": "awaiting_approval"}],
        "wouldPause": {"tool": "place_wire_hold", "gate": "Approval"},
    }
    view = turn_from_test(data)
    assert _status(EvalCheck("pauses_on", tool="place_wire_hold"), view) == "pass"
    assert _status(EvalCheck("pauses_for", kind="approval"), view) == "pass"
    sent: Json = {"reply": "Done.", "toolCalls": [{"name": "place_wire_hold", "status": "ok"}]}
    assert _status(EvalCheck("pauses_on", tool="place_wire_hold"), turn_from_test(sent)) == "fail"


def test_typed_answer_cost_and_not_called_checks() -> None:
    view = turn_from_test(
        {
            "reply": "Declined.",
            "toolCalls": [{"name": "score_wire"}],
            "output": {"decision": "decline", "reason": "limit"},
            "costUsd": 0.04,
            "tookMs": 1500,
        }
    )
    assert (
        _status(EvalCheck("output_matches", fields={"decision": "decline", "reason": {"$exists": True}}), view)
        == "pass"
    )
    assert _status(EvalCheck("output_matches", fields={"decision": "approve"}), view) == "fail"
    assert _status(EvalCheck("output_matches", fields={"note": {"$exists": True}}), view) == "fail"
    assert _status(EvalCheck("within", max_cost_usd=0.05, max_seconds=2), view) == "pass"
    assert _status(EvalCheck("within", max_seconds=1), view) == "fail"
    assert _status(EvalCheck("not_calls_tool", tool="place_wire_hold"), view) == "pass"
    assert _status(EvalCheck("not_calls_tool", tool="score_wire"), view) == "fail"
