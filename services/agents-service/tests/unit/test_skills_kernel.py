"""Skills in the kernel (c-063 T010), by failure mode: an on-match skill missing from the index or its body sent before
it loads; an always-on body left out; a load past two skills or the token budget accepted; load_skill charged to the
tool-call budget; a loaded skill's guardrails not applied, or applied when it never loaded; a load not recorded."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from dataclasses import replace
from typing import Any

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel

from ops_agent_kernel import skills as skillset
from ops_agent_kernel.events import SkillLoaded, TextReplaced
from ops_agent_kernel.kernel import run_turn
from ops_agent_kernel.ports import KernelPorts, ToolOutcome
from ops_agent_kernel.types import AgentSettings, PromptFragment, Resume, Skill, ToolGrant, TurnRequest, TurnResult

HARDSHIP = Skill(
    "sk_1",
    1,
    "Hardship request triage",
    "hardship-request-triage",
    "The customer cannot pay because of a hardship.",
    "on_match",
    "Steps: record the reason, offer the hardship form.",
    ("payment deferral promise",),
    40,
)
DISCLOSURE = Skill(
    "sk_2", 3, "Bank disclosure", "bank-disclosure", "", "always", "End with: Northfield Bank, member CDIC."
)


class NoTools:
    async def execute(
        self, tool: str, arguments: dict[str, Any], *, key: str, approval_token: str | None
    ) -> ToolOutcome:
        raise AssertionError("no tool runs")


class NoKnowledge:
    async def search(self, query: str, kb_ids: list[str], *, k: int) -> list[Any]:
        return []


def _last_user(messages: list[ModelMessage]) -> str:
    for m in reversed(messages):
        if isinstance(m, ModelRequest):
            for p in m.parts:
                if isinstance(p, UserPromptPart) and isinstance(p.content, str):
                    return p.content
    return ""


class Model:
    """Loads the slugs in `loads` one call at a time, then answers `answer`. Classification calls answer
    `classify(message)`. Records each answering request's instructions and offered tools."""

    def __init__(self, loads: list[str], answer: str, classify: Callable[[str], str] = lambda m: "none") -> None:
        self.loads, self.answer, self.classify = list(loads), answer, classify
        self.instructions: list[str] = []
        self.results: list[Any] = []

    def respond(self, messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        prompt = _last_user(messages)
        if prompt.startswith("Blocked topics:"):
            return ModelResponse(
                parts=[ToolCallPart("final_result", {"topic": self.classify(prompt.split("Message:\n", 1)[1])})]
            )
        self.instructions.append(str(info.instructions or ""))
        last = messages[-1]
        if isinstance(last, ModelRequest):
            self.results += [p.content for p in last.parts if isinstance(p, ToolReturnPart)]
        if self.loads:
            return ModelResponse(
                parts=[ToolCallPart("load_skill", {"slug": self.loads.pop(0), "matched": "cannot pay"})]
            )
        return ModelResponse(parts=[TextPart(self.answer)])

    def build(self) -> FunctionModel:
        async def stream(
            messages: list[ModelMessage], info: AgentInfo
        ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
            for i, part in enumerate(self.respond(messages, info).parts):
                if isinstance(part, TextPart):
                    yield part.content
                elif isinstance(part, ToolCallPart):
                    yield {i: DeltaToolCall(name=part.tool_name, json_args=json.dumps(part.args))}

        return FunctionModel(self.respond, stream_function=stream)


async def turn(model: Model, skills: list[Skill], *, max_tool_calls: int = 6) -> tuple[TurnResult, list[Any]]:
    settings = AgentSettings(
        "ag_advisor", 1, [PromptFragment("You help bankers.")], "m", max_tool_calls=max_tool_calls, skills=skills
    )
    req = TurnRequest("t1", "r1", settings, [], user_turn="My client lost her job and cannot pay this month.")
    events = [
        e async for e in run_turn(req, KernelPorts(model=model.build(), tools=NoTools(), knowledge=NoKnowledge()))
    ]
    return events[-1].result, events  # type: ignore[attr-defined]


def _skill(n: int, tokens: int = 40) -> Skill:
    return Skill(f"sk_x{n}", 1, f"Skill {n}", f"skill-{n}", f"Use for case {n}.", "on_match", f"Body {n}.", (), tokens)


async def test_the_index_lists_on_match_skills_and_always_bodies_follow_the_instructions() -> None:
    model = Model([], "Here is what I found.")
    result, events = await turn(model, [HARDSHIP, DISCLOSURE])
    sent = model.instructions[0]
    assert "- hardship-request-triage: The customer cannot pay because of a hardship." in sent
    assert HARDSHIP.instructions not in sent, "an on-match body waits for load_skill"
    assert sent.index("You help bankers.") < sent.index(DISCLOSURE.instructions)
    assert result.skills == [{"skillId": "sk_2", "name": "Bank disclosure", "version": 3, "matched": "Always on"}]
    assert SkillLoaded("sk_2", 3, "Bank disclosure", "Always on") in events


async def test_load_skill_returns_the_body_records_the_load_and_costs_no_tool_call() -> None:
    model = Model(["hardship-request-triage"], "I recorded the reason and offered the hardship form.")
    result, events = await turn(model, [HARDSHIP], max_tool_calls=0)
    assert result.status == "completed", result
    assert HARDSHIP.instructions in json.dumps(model.results)
    assert result.skills == [
        {"skillId": "sk_1", "name": "Hardship request triage", "version": 1, "matched": "cannot pay"}
    ]
    assert SkillLoaded("sk_1", 1, "Hardship request triage", "cannot pay") in events


async def test_a_third_load_in_one_reply_is_refused() -> None:
    model = Model(["skill-1", "skill-2", "skill-3"], "Done.")
    result, _ = await turn(model, [_skill(1), _skill(2), _skill(3)])
    assert [s["skillId"] for s in result.skills] == ["sk_x1", "sk_x2"]
    assert "At most 2 skills" in json.dumps(model.results)


async def test_a_load_past_the_token_budget_is_refused() -> None:
    model = Model(["skill-1", "skill-2"], "Done.")
    result, _ = await turn(model, [_skill(1, tokens=5000), _skill(2, tokens=2000)])
    assert [s["skillId"] for s in result.skills] == ["sk_x1"]
    assert "6000-token skill budget" in json.dumps(model.results)


def _deferral(message: str) -> str:
    return "payment deferral promise" if "deferral" in message.lower() else "none"


async def test_a_loaded_skills_guardrail_replaces_an_answer_that_breaks_it() -> None:
    model = Model(["hardship-request-triage"], "I promise a payment deferral for three months.", _deferral)
    result, events = await turn(model, [HARDSHIP])
    assert result.stop_reason == "guardrail", result
    assert "deferral" not in result.text and "skill does not allow it" in result.text
    # A skill's guardrail never holds: the answer streamed, so the refusal replaced it on screen.
    assert result.retracted == "I promise a payment deferral for three months."
    assert isinstance(events[-2], TextReplaced) and "deferral" not in events[-2].text, events[-3:]


async def test_a_skills_own_refusal_is_what_the_person_reads() -> None:
    # Shared, 2026-10-18: "I can't help with that here: the Hardship request triage skill does not allow it." gave the
    # banker no next step; the skill's own refusal offers one.
    offer = "I can't promise a deferral, but I can start a hardship request now; the team replies in two days."
    model = Model(["hardship-request-triage"], "I promise a payment deferral for three months.", _deferral)
    result, _ = await turn(model, [replace(HARDSHIP, refusal=offer)])
    assert (result.stop_reason, result.text) == ("guardrail", offer), result


async def test_a_guardrail_from_a_skill_loaded_mid_turn_is_recorded_as_checked() -> None:
    model = Model(["hardship-request-triage"], "The hardship team will review the request.", _deferral)
    result, _ = await turn(model, [HARDSHIP])
    assert result.stop_reason == "final", result
    expected = [
        {"guardrailId": g.guardrail_id, "version": g.version, "name": g.name}
        for g in dict.fromkeys(skillset.guardrails_of(HARDSHIP))
    ]
    assert expected and result.guardrails_checked == expected, (result.guardrails_checked, expected)


async def test_a_skills_guardrail_does_not_apply_when_it_never_loaded() -> None:
    model = Model([], "A payment deferral is something the hardship team decides.", _deferral)
    result, _ = await turn(model, [HARDSHIP])
    assert (result.stop_reason, result.text) == ("final", "A payment deferral is something the hardship team decides.")


HOLD = ToolGrant("place_hold", "bank", "Places a hold on a payment.", "write", {"type": "object", "properties": {}})


class Recording:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def execute(
        self, tool: str, arguments: dict[str, Any], *, key: str, approval_token: str | None
    ) -> ToolOutcome:
        self.calls.append(tool)
        return ToolOutcome(True, {"held": True})


class Script:
    """Answering requests take the next action: ("load", slug), ("call", tool) or ("say", text). Classification calls
    answer `classify(message)`."""

    def __init__(self, actions: list[tuple[str, str]], classify: Callable[[str], str] = lambda m: "none") -> None:
        self.actions, self.classify = list(actions), classify
        self.answered = 0

    def respond(self, messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        prompt = _last_user(messages)
        if prompt.startswith("Blocked topics:"):
            return ModelResponse(
                parts=[ToolCallPart("final_result", {"topic": self.classify(prompt.split("Message:\n", 1)[1])})]
            )
        self.answered += 1
        kind, value = self.actions.pop(0)
        if kind == "load":
            return ModelResponse(parts=[ToolCallPart("load_skill", {"slug": value, "matched": "cannot pay"})])
        if kind == "call":
            return ModelResponse(parts=[ToolCallPart(value, {})])
        return ModelResponse(parts=[TextPart(value)])

    def build(self) -> FunctionModel:
        async def stream(
            messages: list[ModelMessage], info: AgentInfo
        ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
            for i, part in enumerate(self.respond(messages, info).parts):
                if isinstance(part, TextPart):
                    yield part.content
                elif isinstance(part, ToolCallPart):
                    yield {i: DeltaToolCall(name=part.tool_name, json_args=json.dumps(part.args))}

        return FunctionModel(self.respond, stream_function=stream)


async def _run(req: TurnRequest, model: Script, tools: Recording) -> tuple[TurnResult, list[Any]]:
    events = [e async for e in run_turn(req, KernelPorts(model=model.build(), tools=tools, knowledge=NoKnowledge()))]
    return events[-1].result, events  # type: ignore[attr-defined]


async def test_a_skill_loaded_before_an_approval_still_guards_the_answer_after_it() -> None:
    settings = AgentSettings("ag_advisor", 1, [PromptFragment("You help bankers.")], "m", skills=[HARDSHIP])
    tools = Recording()
    first, _ = await _run(
        TurnRequest("t1", "th1", settings, [HOLD], user_turn="My client cannot pay; hold the payment."),
        Script([("load", "hardship-request-triage"), ("call", "place_hold")]),
        tools,
    )
    assert first.status == "interrupted" and first.interrupt is not None
    assert [s["skillId"] for s in first.interrupt.loaded_skills] == ["sk_1"]
    resume = Resume(first.interrupt, "approved", approval_token="tok")
    after, events = await _run(
        TurnRequest("t2", "th1", settings, [HOLD], resume=resume),
        Script([("say", "Done, and I promise a payment deferral.")], _deferral),
        tools,
    )
    assert tools.calls == ["place_hold"]
    assert after.stop_reason == "guardrail", after
    assert "deferral" not in after.text
    assert [s["skillId"] for s in after.skills] == ["sk_1"], "the resumed turn still lists the skill it loaded"
    assert not any(isinstance(e, SkillLoaded) for e in events), "a load is journalled once, before the pause"


async def test_an_always_on_skills_guardrail_refuses_the_question() -> None:
    policy = Skill(
        "sk_3", 1, "Advice policy", "advice-policy", "", "always", "Never give advice.", ("investment advice",), 10
    )
    settings = AgentSettings("ag_advisor", 1, [PromptFragment("You help bankers.")], "m", skills=[policy])
    model = Script([("say", "Buy them.")], lambda m: "investment advice" if "shares" in m else "none")
    result, _ = await _run(
        TurnRequest("t1", "th1", settings, [], user_turn="Should she buy Northfield shares?"), model, Recording()
    )
    assert (result.stop_reason, model.answered) == ("guardrail", 0), result
    assert result.guardrail is not None and result.guardrail["when"] == "before"


async def test_always_on_bodies_do_not_use_the_on_match_budget() -> None:
    big_always = Skill("sk_4", 1, "Long disclosure", "long-disclosure", "", "always", "Disclosure.", (), 5000)
    model = Model(["skill-1"], "Done.")
    result, _ = await turn(model, [big_always, _skill(1, tokens=2000)])
    assert [s["skillId"] for s in result.skills] == ["sk_4", "sk_x1"], result.skills


async def test_the_matched_words_are_one_short_line_in_the_journal() -> None:
    model = Model([], "Done.")
    model.loads = ["hardship-request-triage"]
    original = model.respond

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        out = original(messages, info)
        for p in out.parts:
            if isinstance(p, ToolCallPart) and p.tool_name == "load_skill":
                p.args = {"slug": "hardship-request-triage", "matched": "cannot\npay " + "x" * 500}
        return out

    model.respond = respond  # type: ignore[method-assign]
    result, _ = await turn(model, [HARDSHIP])
    matched = result.skills[0]["matched"]
    assert "\n" not in matched and len(matched) <= 200, matched


async def test_load_skill_refuses_a_slug_the_agent_has_not_attached() -> None:
    model = Model(["someone-elses-skill"], "Done.")
    result, events = await turn(model, [HARDSHIP])
    assert result.skills == [] and not any(isinstance(e, SkillLoaded) for e in events)
    assert "No skill named someone-elses-skill" in json.dumps(model.results)
