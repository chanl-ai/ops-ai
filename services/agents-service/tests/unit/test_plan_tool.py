"""The plan tool, by failure mode: two steps doing at once, a done step reopened or renamed, endless replanning, a
step that spends the whole turn's budget, a plan title that shows personal data, a plan lost at a pause, a finished
plan left open, and a plan an earlier turn left open forgotten by the next."""

from __future__ import annotations

import copy
from dataclasses import replace
from typing import Any

from ops_agent_kernel import plan as planner
from ops_agent_kernel import steps as skill_steps
from ops_agent_kernel.contract import ModelEndpoint
from ops_agent_kernel.events import ToolOutput, TurnFinished
from ops_agent_kernel.kernel import run_turn
from ops_agent_kernel.ports import KernelPorts, ToolOutcome
from ops_agent_kernel.steps import SkillProgram
from ops_agent_kernel.testing import Answer, Reply, ToolCall, system_text
from ops_agent_kernel.types import (
    AgentSettings,
    Interrupt,
    PendingCall,
    Plan,
    PlanStep,
    PromptFragment,
    Skill,
    ToolGrant,
    TurnRequest,
    TurnResult,
)
from ops_agents.activities.catalog import load_catalog
from ops_agents.api.chat_history import history_entry
from ops_agents.api.chat_threads import THINK_HARDER, AssistantBuilder
from ops_agents.graphs.common import interrupt_from_state, interrupt_to_state
from ops_contracts.chat import ChatMessage
from ops_contracts.skill_run import SkillRunState
from ops_service_kit.http import Json, JsonValue
from ops_service_kit.narrow import json_list, json_object
from tests.conftest import SEED, model_on

READ = ToolGrant(
    "find_cases", "Ops AI", "Find cases", "read", {"type": "object", "properties": {"q": {"type": "string"}}}
)
SETTINGS = AgentSettings("ag_ops", 1, [PromptFragment("You help.")], "m", max_tool_calls=1, max_steps=4)


def steps(*statuses: str) -> list[PlanStep]:
    return [{"title": f"Step {i + 1}", "status": s} for i, s in enumerate(statuses)]


def step_args(*statuses: str) -> list[JsonValue]:
    return [{"title": f"Step {i + 1}", "status": s} for i, s in enumerate(statuses)]


def plan_of(*statuses: str) -> Plan:
    return {"title": "t", "steps": steps(*statuses)}


def plan_args(*statuses: str, title: str = "t") -> Json:
    return {"title": title, "steps": step_args(*statuses)}


def plan_call(*statuses: str, **more: Any) -> ToolCall:
    return ToolCall("plan", {"title": "Check the loan files", "steps": step_args(*statuses), **more})


class Reads:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def execute(self, tool: str, arguments: Json, *, key: str, approval_token: str | None) -> ToolOutcome:
        self.calls.append(tool)
        return ToolOutcome(True, {"cases": [{"title": "Renewal"}]})


class NoKnowledge:
    async def search(self, query: str, kb_ids: list[str]) -> list[Any]:
        return []


def scripted(*responses: list[ToolCall] | str) -> tuple[ModelEndpoint, list[str]]:
    """A model that answers each request with the next response: a list of tool calls, or text. Records the system
    instructions it was sent."""
    queue = list(responses)
    seen: list[str] = []

    def script(messages: list[Json], tools: list[Json]) -> Answer:
        seen.append(system_text(messages))
        r = queue.pop(0) if queue else "Done."
        return r if isinstance(r, str) else Reply(tool_calls=r)

    return model_on(script), seen


def rows(part: JsonValue) -> list[Json]:
    """The drawn plan's step rows."""
    return [json_object(row) for row in json_list(json_object(part)["data"])]


def hint_title(part: JsonValue) -> JsonValue:
    return json_object(json_object(part)["hint"])["title"]


async def run(model: ModelEndpoint, req: TurnRequest) -> tuple[TurnResult, list[Any]]:
    events = [e async for e in run_turn(req, KernelPorts(model=model, tools=Reads(), knowledge=NoKnowledge()))]
    last = events[-1]
    assert isinstance(last, TurnFinished)
    return last.result, events


async def plans(model: ModelEndpoint, req: TurnRequest) -> tuple[TurnResult, list[Json]]:
    """The turn's result and each plan part as it was drawn: an event's record changes after it is sent."""
    drawn: list[Json] = []
    result: TurnResult | None = None
    async for e in run_turn(req, KernelPorts(model=model, tools=Reads(), knowledge=NoKnowledge())):
        if isinstance(e, ToolOutput) and e.call.tool == "plan" and e.call.view:
            drawn.append(json_object(copy.deepcopy(e.call.view["part"])))
        if isinstance(e, TurnFinished):
            result = e.result
    assert result is not None
    return result, drawn


def test_one_step_at_a_time_forward_only_and_finished_titles_kept() -> None:
    before = plan_of("done", "doing", "todo")
    assert "One step" in str(planner.check(None, plan_of("doing", "doing", "todo"), replan=False, replans=0))
    assert "cannot go back" in str(planner.check(before, plan_of("done", "todo", "todo"), replan=False, replans=0))
    renamed: Plan = {"title": "t", "steps": [{"title": "Other", "status": "done"}, *steps("done", "doing", "todo")[1:]]}
    assert "keeps its title" in str(planner.check(before, renamed, replan=False, replans=0))
    assert planner.check(before, plan_of("done", "done", "doing"), replan=False, replans=0) is None


def test_a_third_replan_is_refused() -> None:
    before = plan_of("done", "blocked", "todo")
    again = plan_of("done", "doing", "todo")
    assert planner.check(before, again, replan=True, replans=1) is None
    assert "finish with what you have" in str(planner.check(before, again, replan=True, replans=2))


def test_a_step_title_is_masked_as_reply_text_is() -> None:
    plan, _ = planner.given(plan_args("doing", "todo", "todo", title="Card 4111 1111 1111 1111"))
    assert plan is not None and "4111" not in plan["title"], plan


async def test_the_plan_ticks_itself_each_step_gets_its_own_budget_and_the_done_plan_reads_did_n_steps() -> None:
    # A plan's second step read nothing (the first had spent the turn's one call), and every tick cost a model step.
    model, seen = scripted(
        [plan_call("doing", "todo", "todo"), ToolCall("find_cases", {"q": "open conditions"})],
        [ToolCall("find_cases", {"q": "renewals"})],
        "Two files have open conditions and a renewal this month.",
    )
    result, drawn = await plans(model, TurnRequest("t1", "r1", SETTINGS, [READ], user_turn="Which loan files?"))
    assert result.stop_reason == "final" and len(seen) == 3, (result, len(seen))
    reads = [r for r in result.tool_calls if r.tool == "find_cases"]
    assert [r.status for r in reads] == ["ok", "ok"], reads
    assert [[s["state"] for s in rows(d)] for d in drawn][:2] == [
        ["running", "pending", "pending"],
        ["done", "running", "pending"],
    ]
    assert hint_title(drawn[-1]) == "Did 3 steps" and not any("(skipped)" in str(s["title"]) for s in rows(drawn[-1]))


class NeedsSignIn:
    async def execute(self, tool: str, arguments: Json, *, key: str, approval_token: str | None) -> ToolOutcome:
        return ToolOutcome(False, {"error": {"code": "CONNECTION_NOT_LINKED", "message": "Sign in to Salesforce."}})


async def test_a_turn_stopped_by_a_sign_in_marks_the_step_blocked() -> None:
    model, _ = scripted(
        [plan_call("doing", "todo", "todo"), ToolCall("find_cases", {"q": "open conditions"})],
        "Connect Salesforce to go on.",
    )
    req = TurnRequest("t1", "r1", SETTINGS, [READ], user_turn="Which loan files?")
    events = [e async for e in run_turn(req, KernelPorts(model=model, tools=NeedsSignIn(), knowledge=NoKnowledge()))]
    last = [e.call for e in events if isinstance(e, ToolOutput) and e.call.tool == "plan"][-1]
    assert last.view is not None
    part = json_object(last.view["part"])
    assert [s["state"] for s in rows(part)] == ["failed", "pending", "pending"]
    assert str(rows(part)[0]["title"]).endswith("waiting for you")
    assert planner.from_part(part) is not None


async def test_an_answer_with_nothing_waiting_finishes_the_plan() -> None:
    # A complete answer left its last step drawn as blocked, because the model made no plan call after the last read.
    model, _ = scripted(
        [plan_call("done", "done", "doing"), ToolCall("find_cases", {"q": "renewals"})],
        "Two files have open conditions.",
    )
    _, events = await run(model, TurnRequest("t1", "r1", SETTINGS, [READ], user_turn="Which loan files?"))
    last = [e.call for e in events if isinstance(e, ToolOutput) and e.call.tool == "plan"][-1]
    assert last.view is not None and hint_title(last.view["part"]) == "Did 3 steps", last.view


async def test_a_plan_left_open_goes_on_at_its_blocked_step_in_two_model_calls() -> None:
    # After a sign-in the resumed plan took seven model calls: plan updates in steps of their own around two reads.
    carried = plan_args("done", "blocked", "todo", title="Check the loan files")
    model, seen = scripted([ToolCall("find_cases", {"q": "renewals"})], "Finished.")
    req = TurnRequest(
        "t2", "r2", SETTINGS, [READ], user_turn="I connected Salesforce. Please go ahead.", carried_plan=carried
    )
    result, drawn = await plans(model, req)
    assert "## Plan in progress: Check the loan files" in seen[0], seen[0]
    assert len(seen) == 2 and [r.status for r in result.tool_calls if r.tool == "find_cases"] == ["ok"]
    assert [s["state"] for s in rows(drawn[0])] == ["done", "failed", "pending"]
    assert hint_title(drawn[-1]) == "Did 3 steps" and not any("(skipped)" in str(s["title"]) for s in rows(drawn[-1]))


def test_the_chat_keeps_one_plan_part_on_top_and_hands_an_open_plan_to_the_next_turn() -> None:
    builder = AssistantBuilder(load_catalog(SEED), ChatMessage(id="m1", role="assistant", content="", at="t"))
    read: dict[str, Any] = {
        "id": "c1",
        "tool": "find_cases",
        "server": "Ops AI",
        "input": {},
        "status": "ok",
        "output": [{"a": 1}],
    }
    table = {"type": "widget", "id": "", "shape": "rows", "data": [{"a": 1}]}
    builder.apply("tool_call", {**read, "view": {"part": table}})
    for i, statuses in enumerate((("doing", "todo", "todo"), ("done", "blocked", "todo"))):
        drawn = planner.part({"title": "Check", "steps": steps(*statuses)})
        builder.apply(
            "tool_call",
            {"id": f"p{i}", "tool": "plan", "server": "kernel", "input": {}, "status": "ok", "view": {"part": drawn}},
        )
    parts = builder.message.parts or []
    assert [p.id for p in parts] == ["wp_plan", "wp_c1"], [p.id for p in parts]
    carried: dict[str, Any] = history_entry(builder.message)
    assert carried["plan"]["steps"][1]["status"] == "blocked" and "reads" in carried, carried
    # An approval pause keeps the plan, the running skill and the tools a stopped skill holds through the run's
    # saved state: the resumed turn is the same reply and goes on at the same step.
    call = PendingCall("c", "k", "a", "t", "s", "write", {}, "h")
    program = SkillProgram.model_validate({"steps": [{"do": "Ask which charge."}, {"do": "Open the dispute."}]})
    skill = replace(
        Skill("sk_open", 1, "Open a dispute", "open-a-dispute", "Disputes.", "on_match", ""), program=program
    )
    run = skill_steps.start(SkillRunState(), skill, [skill], by="model")
    held = {"sk_refund": ["refund_charge"]}
    kept = Interrupt(
        "i",
        "approval",
        "Approval",
        call,
        b"[]",
        [],
        {"title": "Check", "steps": steps("done", "blocked", "todo")},
        run,
        held,
    )
    back = interrupt_from_state(interrupt_to_state(kept))
    assert back.plan == kept.plan
    assert back.run == run and back.run is not None and back.run.running is not None, back.run
    assert back.held == held, back.held


def test_think_harder_is_offered_on_a_planned_reply_and_not_on_one_already_run_deeper() -> None:
    def built(model: str) -> list[str]:
        b = AssistantBuilder(
            load_catalog(SEED), ChatMessage(id="m", role="assistant", content="", at="t"), think_alias="thinking"
        )
        drawn = planner.part({"title": "Check", "steps": steps("done", "done", "done")})
        b.apply(
            "tool_call",
            {"id": "p", "tool": "plan", "server": "kernel", "input": {}, "status": "ok", "view": {"part": drawn}},
        )
        b.apply("turn", {"model": model})
        return list(b.message.follow_ups or [])

    assert built("assistant") == [THINK_HARDER]
    assert built("thinking") == []


def test_a_carried_plan_is_never_asked_to_be_sent_again() -> None:
    # The resumed turn's prompt asked the model to send the whole plan, though the plan tool is withdrawn once a plan
    # exists: each try was an unknown-tool retry, four model calls before the first read.
    told = planner.prompt({"title": "Check", "steps": steps("done", "blocked", "todo")})
    assert "send the whole plan" not in told and "do not call plan" in told, told
