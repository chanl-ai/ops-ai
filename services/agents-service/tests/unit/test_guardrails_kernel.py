"""Blocked-topic guardrails in the kernel (c-063 T003 to T005), by failure mode: a blocked question answered anyway,
the answering model called for a question the guardrail refuses, an answer that drifts into a blocked topic shown,
a correction that is not tried before refusing, a check that passes when it cannot run or returns nonsense, and an
agent with no guardrail paying for a classification call."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from typing import Any, cast

import pytest
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, TextPart, ToolCallPart, UserPromptPart
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel

from ops_agent_kernel import aliases, guard
from ops_agent_kernel.events import KernelEvent, StatusChanged, TextDelta, TextReplaced, TurnFinished
from ops_agent_kernel.kernel import run_turn
from ops_agent_kernel.ports import KernelPorts, ToolOutcome
from ops_agent_kernel.types import AgentSettings, Guardrail, PromptFragment, Skill, ToolGrant, TurnRequest, TurnResult

NO_ADVICE = Guardrail("gr_1", 2, "No investment advice", ("investment advice",), "I can't give investment advice.")
# The same rule held until checked: the answer is never on screen before its check passes.
HELD = Guardrail(
    "gr_1", 2, "No investment advice", ("investment advice",), "I can't give investment advice.", hold=True
)


def screen(events: list[KernelEvent]) -> str:
    """What the person sees at the end: each delta appended, each replacement taking the place of what was there."""
    shown = ""
    for e in events:
        if isinstance(e, TextDelta):
            shown += e.delta
        elif isinstance(e, TextReplaced):
            shown = e.text
    return shown


class NoTools:
    async def execute(
        self, tool: str, arguments: dict[str, Any], *, key: str, approval_token: str | None
    ) -> ToolOutcome:
        raise AssertionError("no tool runs")


class NoKnowledge:
    async def search(self, query: str, kb_ids: list[str], *, k: int) -> list[Any]:
        return []


def _prompt(messages: list[ModelMessage]) -> str:
    for m in reversed(messages):
        if isinstance(m, ModelRequest):
            for p in m.parts:
                if isinstance(p, UserPromptPart) and isinstance(p.content, str):
                    return p.content
    return ""


class Model:
    """Answers classification calls with `classify(message)` and answering calls with `answers` in order."""

    def __init__(self, classify: Callable[[str], Any], answers: list[str | Exception]) -> None:
        self.classify, self.answers = classify, list(answers)
        self.checks: list[str] = []
        # Every classification prompt whole, topics list included.
        self.check_prompts: list[str] = []
        self.answered = 0
        # The tools each answering request offered, in order.
        self.offered: list[list[str]] = []

    def respond(self, messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        prompt = _prompt(messages)
        if prompt.startswith("Blocked topics:"):
            message = prompt.split("Message:\n", 1)[1]
            self.check_prompts.append(prompt)
            self.checks.append(message)
            out = self.classify(message)
            if isinstance(out, Exception):
                raise out
            return ModelResponse(parts=[ToolCallPart("final_result", out)])
        self.answered += 1
        self.offered.append([t.name for t in info.function_tools])
        answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(answer, Exception):
            raise answer
        return ModelResponse(parts=[TextPart(answer)])

    def build(self) -> FunctionModel:
        async def stream(
            messages: list[ModelMessage], info: AgentInfo
        ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
            for i, part in enumerate(self.respond(messages, info).parts):
                if isinstance(part, TextPart):
                    # Word by word, as a provider streams, so a test can tell a streamed answer from a whole one.
                    for n, word in enumerate(part.content.split(" ")):
                        yield word if n == 0 else f" {word}"
                elif isinstance(part, ToolCallPart):
                    yield {i: DeltaToolCall(name=part.tool_name, json_args=json.dumps(part.args))}

        return FunctionModel(self.respond, stream_function=stream)


def topic_when(words: str) -> Callable[[str], dict[str, str]]:
    return lambda m: {"topic": "investment advice" if words in m.lower() else "none", "reason": "test"}


LOOKUP = ToolGrant("lookup", "bank", "Looks up a customer.", "read", {"type": "object", "properties": {}})


async def turn(
    model: Model, question: str, rules: list[Guardrail] | None = None, *, tools: bool = False
) -> tuple[TurnResult, str]:
    settings = AgentSettings("ag_advisor", 1, [PromptFragment("You help bankers.")], "m", guardrails=rules or [])
    req = TurnRequest("t1", "r1", settings, [LOOKUP] if tools else [], user_turn=question)
    ports = KernelPorts(model=model.build(), tools=NoTools(), knowledge=NoKnowledge())
    events = [e async for e in run_turn(req, ports)]
    return events[-1].result, screen(events)  # type: ignore[attr-defined]


async def test_a_blocked_question_gets_the_message_and_no_answering_call() -> None:
    model = Model(topic_when("shares"), ["Buy them."])
    result, streamed = await turn(model, "Should my client buy Harbor & Pine shares?", [NO_ADVICE])
    assert (result.status, result.stop_reason, result.text, streamed) == (
        "completed",
        "guardrail",
        NO_ADVICE.message,
        NO_ADVICE.message,
    )
    assert result.guardrail == {
        "guardrailId": "gr_1",
        "version": 2,
        "name": "No investment advice",
        "topic": "investment advice",
        "when": "before",
    }
    assert model.answered == 0, "the answering model is never called"


async def test_an_allowed_question_is_answered_after_both_checks() -> None:
    model = Model(topic_when("shares"), ["The wire fee is 25.00."])
    result, streamed = await turn(model, "What is the fee for an outgoing wire?", [NO_ADVICE])
    assert (result.stop_reason, result.text, streamed) == ("final", "The wire fee is 25.00.", "The wire fee is 25.00.")
    assert model.checks == ["What is the fee for an outgoing wire?", "The wire fee is 25.00."]


async def test_a_drifting_answer_is_corrected_once_by_a_tool_less_call() -> None:
    model = Model(topic_when("invest in"), ["You should invest in our fund.", "The fund's fee is 1 percent."])
    result, streamed = await turn(model, "Tell me about the fund", [NO_ADVICE], tools=True)
    assert (result.stop_reason, result.text) == ("final", "The fund's fee is 1 percent."), result
    assert streamed == "The fund's fee is 1 percent.", "the screen ends on the checked answer alone"
    assert result.guardrail is not None and result.guardrail["when"] == "corrected"
    assert "lookup" in model.offered[0] and model.offered[1] == [], "the correction offers no tool"


async def test_an_answer_that_drifts_twice_is_replaced_by_the_message() -> None:
    model = Model(topic_when("invest in"), ["You should invest in our fund."])
    result, _ = await turn(model, "Tell me about the fund", [NO_ADVICE])
    assert (result.stop_reason, result.text) == ("guardrail", NO_ADVICE.message)
    assert result.guardrail is not None and result.guardrail["when"] == "after"


async def test_a_check_that_cannot_run_fails_closed() -> None:
    model = Model(lambda m: RuntimeError("models-service down"), ["Buy them."])
    result, streamed = await turn(model, "What is the fee for a wire?", [NO_ADVICE])
    assert (result.status, result.stop_reason, result.error_code) == (
        "failed",
        "guardrail_unavailable",
        "guardrail_unavailable",
    )
    assert model.answered == 0 and "could not check" in streamed


async def test_a_check_returning_a_topic_it_was_not_given_fails_closed() -> None:
    model = Model(lambda m: {"topic": "weather"}, ["Sunny."])
    result, _ = await turn(model, "What is the fee for a wire?", [NO_ADVICE])
    assert (result.status, result.stop_reason) == ("failed", "guardrail_unavailable"), result


async def test_an_agent_without_guardrails_makes_no_check() -> None:
    model = Model(topic_when("shares"), ["Buy them."])
    result, streamed = await turn(model, "Should my client buy Harbor & Pine shares?")
    assert (result.stop_reason, result.text, streamed, model.checks) == ("final", "Buy them.", "Buy them.", [])


async def test_a_correction_that_fails_ends_with_the_guardrail_message() -> None:
    model = Model(topic_when("invest in"), ["You should invest in our fund.", RuntimeError("provider down")])
    result, streamed = await turn(model, "Tell me about the fund", [NO_ADVICE])
    assert (result.stop_reason, result.text, streamed) == ("guardrail", NO_ADVICE.message, NO_ADVICE.message)
    assert "invest in" not in streamed


async def test_a_held_answer_is_sent_whole_after_the_check() -> None:
    model = Model(topic_when("shares"), ["The wire fee is 25.00."])
    settings = AgentSettings("ag_advisor", 1, [PromptFragment("You help bankers.")], "m", guardrails=[HELD])
    req = TurnRequest("t1", "r1", settings, [], user_turn="What is the wire fee?")
    events = [
        e async for e in run_turn(req, KernelPorts(model=model.build(), tools=NoTools(), knowledge=NoKnowledge()))
    ]
    deltas = [e.delta for e in events if isinstance(e, TextDelta)]
    assert len(deltas) == 1, deltas
    assert StatusChanged("checking") in events


async def test_a_guarded_answer_streams_as_written_and_a_passing_check_sends_no_second_copy() -> None:
    # Chat on shared, 2026-10-18: a guarded agent showed nothing until the whole answer and its check were done.
    model = Model(topic_when("shares"), ["The wire fee is 25.00."])
    settings = AgentSettings("ag_advisor", 1, [PromptFragment("You help bankers.")], "m", guardrails=[NO_ADVICE])
    req = TurnRequest("t1", "r1", settings, [], user_turn="What is the wire fee?")
    events = [
        e async for e in run_turn(req, KernelPorts(model=model.build(), tools=NoTools(), knowledge=NoKnowledge()))
    ]
    deltas = [e for e in events if isinstance(e, TextDelta)]
    assert len(deltas) > 1 and "".join(d.delta for d in deltas) == "The wire fee is 25.00.", deltas
    assert not any(isinstance(e, TextReplaced) for e in events)
    first, checking = events.index(deltas[0]), events.index(StatusChanged("checking"))
    assert first < checking, "text is on screen before the after-answer check runs"
    result = cast(TurnFinished, events[-1]).result
    assert (result.text, result.retracted) == ("The wire fee is 25.00.", None)


async def test_a_streamed_answer_the_check_refuses_is_replaced_and_recorded_as_retracted() -> None:
    model = Model(topic_when("invest in"), ["You should invest in our fund."])
    result, shown = await turn(model, "Tell me about the fund", [NO_ADVICE])
    assert (result.text, shown) == (NO_ADVICE.message, NO_ADVICE.message), "the refusal replaces what streamed"
    assert (result.retracted, result.withheld) == ("You should invest in our fund.", None)


@pytest.mark.parametrize("rule", [NO_ADVICE, HELD], ids=["streamed", "held"])
async def test_a_refused_answer_never_stays_on_screen(rule: Guardrail) -> None:
    model = Model(topic_when("invest in"), ["You should invest in our fund."])
    result, shown = await turn(model, "Tell me about the fund", [rule])
    assert "invest in" not in shown and result.text == rule.message, shown


async def test_an_agent_without_guardrails_streams_word_by_word() -> None:
    model = Model(topic_when("shares"), ["The wire fee is 25.00."])
    settings = AgentSettings("ag_advisor", 1, [PromptFragment("You help bankers.")], "m")
    req = TurnRequest("t1", "r1", settings, [], user_turn="What is the wire fee?")
    events = [
        e async for e in run_turn(req, KernelPorts(model=model.build(), tools=NoTools(), knowledge=NoKnowledge()))
    ]
    assert len([e for e in events if isinstance(e, TextDelta)]) > 1


class Lookups:
    async def execute(
        self, tool: str, arguments: dict[str, Any], *, key: str, approval_token: str | None
    ) -> ToolOutcome:
        return ToolOutcome(True, {"found": True})


def cut_short_model(raise_mid_answer: bool) -> FunctionModel:
    """Classifies everything as none; answers on a blocked topic, then either calls a tool (so the step limit cuts
    the reply) or fails part-way through the answer."""

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if _prompt(messages).startswith("Blocked topics:"):
            return ModelResponse(parts=[ToolCallPart("final_result", {"topic": "none"})])
        return ModelResponse(parts=[TextPart("You should invest in our fund."), ToolCallPart("lookup", {})])

    async def stream(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        if _prompt(messages).startswith("Blocked topics:"):
            yield {0: DeltaToolCall(name="final_result", json_args='{"topic": "none"}')}
            return
        yield "You should invest in our fund."
        if raise_mid_answer:
            raise RuntimeError("provider dropped the stream")
        yield {1: DeltaToolCall(name="lookup", json_args="{}")}

    return FunctionModel(respond, stream_function=stream)


async def _cut_turn(raise_mid_answer: bool) -> tuple[TurnResult, str]:
    settings = AgentSettings(
        "ag_advisor", 1, [PromptFragment("You help bankers.")], "m", max_steps=1, guardrails=[NO_ADVICE]
    )
    req = TurnRequest("t1", "r1", settings, [LOOKUP], user_turn="Tell me about the fund")
    ports = KernelPorts(model=cut_short_model(raise_mid_answer), tools=Lookups(), knowledge=NoKnowledge())
    events = [e async for e in run_turn(req, ports)]
    return events[-1].result, screen(events)  # type: ignore[attr-defined]


async def test_a_guarded_answer_cut_by_the_step_limit_keeps_none_of_its_unchecked_text() -> None:
    result, streamed = await _cut_turn(raise_mid_answer=False)
    assert result.stop_reason == "max_steps", result
    assert "invest in" not in result.text and "invest in" not in streamed, (result.text, streamed)


async def test_a_guarded_answer_cut_by_a_model_error_keeps_none_of_its_unchecked_text() -> None:
    result, streamed = await _cut_turn(raise_mid_answer=True)
    assert result.status == "failed", result
    assert "invest in" not in result.text and "invest in" not in streamed, (result.text, streamed)


async def test_a_topic_scope_pinned_on_the_agent_reaches_the_classifier_prompt() -> None:
    """A bare label lets a real model read "investment advice" as covering the bank's own deposit products, so the
    scope saved on the guardrail version has to survive the pin snapshot, the catalog and the kernel into the prompt."""
    from ops_agents.activities.catalog import AgentDefinition, Catalog, Fragment  # noqa: PLC0415

    scope = "Whether to buy, sell or hold a security. Not: comparing the bank's own deposit accounts."
    pin = {
        "guardrailId": "gr_1",
        "version": 2,
        "name": "No investment advice",
        "kind": "blocked_topics",
        "topics": ["investment advice", "tax advice"],
        "scopes": {"investment advice": scope},
        "message": "I can't give investment advice.",
    }
    agent = AgentDefinition.model_validate(
        {
            "id": "ag_advisor",
            "name": "Advisor",
            "role": "",
            "version": 1,
            "instructions": [Fragment(text="You help bankers.")],
            "tools": [],
            "default_kb_ids": [],
            "suggestions": [],
            "guardrails": [pin],
        }
    )
    catalog = Catalog(agents=[agent], tools=[], datasets={}, passages=[], knowledge_bases=[])
    settings = catalog.settings_for(agent, "m")
    model = Model(topic_when("shares"), ["Savings Plus pays 3.1 percent."])
    req = TurnRequest("t1", "r1", settings, [], user_turn="Compare Savings Plus and Money Market.")
    _ = [e async for e in run_turn(req, KernelPorts(model=model.build(), tools=NoTools(), knowledge=NoKnowledge()))]
    listed = model.check_prompts[0].split("Message:", 1)[0]
    assert f"- investment advice: {scope}\n" in listed, listed
    assert "- tax advice\n" in listed, "a topic with no scope is listed bare"


class Source:
    """models-service by alias: the agent's alias answers with `turn`, `guardrail-check` with `check` (a Model, or an
    exception every call raises)."""

    def __init__(self, turn: Model, check: Model | Exception) -> None:
        self.turn, self.check = turn.build(), check

    def model_for(self, alias: str) -> FunctionModel:
        if alias != guard.GUARD_ALIAS:
            return self.turn
        if isinstance(self.check, Model):
            return self.check.build()
        error = self.check

        def fail(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            raise error

        return FunctionModel(fail)


@pytest.fixture(autouse=True)
def _forget_unbound() -> None:
    aliases._unbound_until.clear()  # pyright: ignore[reportPrivateUsage]


async def through(source: Source, question: str) -> TurnResult:
    settings = AgentSettings("ag_advisor", 1, [PromptFragment("You help bankers.")], "m", guardrails=[NO_ADVICE])
    req = TurnRequest("t1", "r1", settings, [], user_turn=question)
    ports = KernelPorts(model=source.turn, tools=NoTools(), knowledge=NoKnowledge(), models=source)
    events = [e async for e in run_turn(req, ports)]
    return events[-1].result  # type: ignore[attr-defined]


SAVINGS = "Compare Savings Plus and Money Market for her"


async def test_the_check_runs_on_its_own_alias_when_models_service_binds_it() -> None:
    # The answering model reads every question as advice (gpt-5-nano on the scoped topic); the check's model does not.
    answering = Model(lambda m: {"topic": "investment advice", "reason": "test"}, ["Savings Plus pays 3.1 percent."])
    checker = Model(topic_when("shares"), ["unused"])
    result = await through(Source(answering, checker), SAVINGS)
    assert (result.stop_reason, result.text) == ("final", "Savings Plus pays 3.1 percent."), result
    assert checker.checks and not answering.checks, "both checks ran on guardrail-check, none on the agent's model"


async def test_an_unbound_check_alias_uses_the_agents_model() -> None:
    unbound = ModelHTTPError(404, "guardrail-check", {"error": {"code": "alias_not_found"}})
    answering = Model(topic_when("shares"), ["Savings Plus pays 3.1 percent."])
    result = await through(Source(answering, unbound), SAVINGS)
    assert result.stop_reason == "final" and answering.checks, result


async def test_a_failing_check_alias_fails_closed() -> None:
    down = ModelHTTPError(503, "guardrail-check", {"error": {"code": "provider_unavailable"}})
    answering = Model(topic_when("shares"), ["Savings Plus pays 3.1 percent."])
    result = await through(Source(answering, down), SAVINGS)
    assert (result.status, result.stop_reason) == ("failed", "guardrail_unavailable"), result
    assert answering.answered == 0 and not answering.checks, "neither answered nor checked on another model"


async def test_a_guardrail_switched_off_is_never_checked_and_the_turn_says_so() -> None:
    model = Model(topic_when("shares"), ["Buy them."])
    settings = AgentSettings("ag_advisor", 1, [PromptFragment("You help bankers.")], "m", guardrails_off=[NO_ADVICE])
    req = TurnRequest("t1", "r1", settings, [], user_turn="Should my client buy Harbor & Pine shares?")
    events = [
        e async for e in run_turn(req, KernelPorts(model=model.build(), tools=NoTools(), knowledge=NoKnowledge()))
    ]
    result = cast(TurnResult, events[-1].result)  # type: ignore[attr-defined]  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]
    assert (result.stop_reason, result.text) == ("final", "Buy them."), result
    assert model.checks == [], "no classification call for a guardrail that is off"
    off = {"guardrailId": "gr_1", "version": 2, "name": "No investment advice"}
    assert (result.guardrails_checked, result.guardrails_off) == ([], [off])


async def test_a_guardrail_that_is_on_is_named_as_checked() -> None:
    result, _ = await turn(Model(topic_when("shares"), ["The wire fee is 25.00."]), "Wire fee?", [NO_ADVICE])
    assert result.guardrails_checked == [{"guardrailId": "gr_1", "version": 2, "name": "No investment advice"}]
    assert result.guardrails_off == []


async def test_an_agent_guarded_only_by_an_unloaded_skill_still_sends_its_answer() -> None:
    """The advisor with its pinned guardrail off: its hardship skill carries guardrails, so the answer is held back
    from streaming, and with no rule to check it must still be sent whole (seen live: an empty reply)."""
    skill = Skill(
        "sk_1", 1, "Hardship", "hardship", "The customer lost a job", "on_match", "Use the form.", ("crypto",)
    )
    model = Model(topic_when("shares"), ["Savings Plus pays 3.1 percent."])
    settings = AgentSettings("ag_advisor", 1, [PromptFragment("You help bankers.")], "m", skills=[skill])
    req = TurnRequest("t1", "r1", settings, [], user_turn="Compare Savings Plus and Money Market")
    events = [
        e async for e in run_turn(req, KernelPorts(model=model.build(), tools=NoTools(), knowledge=NoKnowledge()))
    ]
    result = cast(TurnResult, events[-1].result)  # type: ignore[attr-defined]  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]
    streamed = "".join(e.delta for e in events if isinstance(e, TextDelta))
    assert (result.text, streamed) == ("Savings Plus pays 3.1 percent.", "Savings Plus pays 3.1 percent."), events
    assert model.checks == [], "nothing to check"


async def test_no_tool_call_cap_lets_a_long_turn_run() -> None:
    calls = {"n": 0}

    class Counting:
        async def execute(
            self, tool: str, arguments: dict[str, Any], *, key: str, approval_token: str | None
        ) -> ToolOutcome:
            calls["n"] += 1
            return ToolOutcome(True, {"done": calls["n"]})

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        made = sum(1 for m in messages if isinstance(m, ModelRequest) for p in m.parts if p.part_kind == "tool-return")
        if made < 9:
            return ModelResponse(parts=[ToolCallPart("lookup", {}, tool_call_id=f"c{made}")])
        return ModelResponse(parts=[TextPart("Done after nine lookups.")])

    async def stream(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        part = respond(messages, info).parts[0]
        if isinstance(part, TextPart):
            yield part.content
        elif isinstance(part, ToolCallPart):
            yield {0: DeltaToolCall(name=part.tool_name, json_args="{}", tool_call_id=part.tool_call_id)}

    for cap, expected in ((None, "final"), (6, "max_tool_calls")):
        calls["n"] = 0
        settings = AgentSettings("ag_x", 1, [PromptFragment("x")], "m", max_tool_calls=cap, max_steps=50)
        req = TurnRequest("t1", "r1", settings, [LOOKUP], user_turn="Look it all up")
        ports = KernelPorts(
            model=FunctionModel(respond, stream_function=stream), tools=Counting(), knowledge=NoKnowledge()
        )
        events = [e async for e in run_turn(req, ports)]
        result = cast(TurnResult, events[-1].result)  # type: ignore[attr-defined]  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]
        assert result.stop_reason == expected, (cap, result.error)


async def test_a_recheck_that_cannot_run_fails_the_turn_closed() -> None:
    seen = {"n": 0}

    def classify(message: str) -> Any:
        seen["n"] += 1
        if seen["n"] == 3:
            return RuntimeError("models-service down")
        return {"topic": "investment advice" if "invest in" in message else "none", "reason": "test"}

    model = Model(classify, ["You should invest in our fund.", "The fund's fee is 1 percent."])
    result, _ = await turn(model, "Tell me about the fund", [NO_ADVICE])
    assert (result.status, result.stop_reason) == ("failed", "guardrail_unavailable"), result


DEFERRAL = "Promising a payment deferral before the hardship team approves it"
HARDSHIP_ALWAYS = Skill(
    "sk_hardship",
    2,
    "Hardship request triage",
    "hardship-request-triage",
    "The customer cannot make a payment because of job loss, illness or another hardship.",
    "always",
    "Steps: say sorry, record the reason, offer the hardship request form.",
    (DEFERRAL,),
    40,
)


def reads_bare_topics_broadly(model: Model) -> Callable[[str], dict[str, str]]:
    """A classifier as the real guardrail model behaved (seed-walk check a): a hardship question falls under the
    deferral topic when the topic is listed bare, and does not once the skill's own scope is listed as not covered."""

    def classify(message: str) -> dict[str, str]:
        listed = model.check_prompts[-1].split("Message:", 1)[0]
        promise = "promise" in message.lower()
        hardship = "lost her job" in message.lower()
        # Each listed line is "- <label>" or "- <label>: <scope>"; a label is answered exactly as listed.
        for line in (x[2:] for x in listed.splitlines() if x.startswith("- ") and x[2:].startswith(DEFERRAL)):
            label, _, scope = line.partition(": ")
            if promise or (hardship and "job loss" not in scope):
                return {"topic": label, "reason": "test"}
        return {"topic": "none", "reason": "test"}

    return classify


async def test_a_skills_guardrail_allows_the_skills_own_scope_and_still_refuses_its_topic() -> None:
    settings = AgentSettings("ag_advisor", 1, [PromptFragment("You help bankers.")], "m", skills=[HARDSHIP_ALWAYS])

    async def ask(question: str) -> tuple[TurnResult, Model]:
        model = Model(lambda m: {"topic": "none"}, ["I'm sorry. The next step is the hardship request form."])
        model.classify = reads_bare_topics_broadly(model)
        req = TurnRequest("t1", "r1", settings, [], user_turn=question)
        ports = KernelPorts(model=model.build(), tools=NoTools(), knowledge=NoKnowledge())
        events = [e async for e in run_turn(req, ports)]
        return events[-1].result, model  # type: ignore[attr-defined]

    helped, model = await ask("My client lost her job and cannot make this month's payment. What can we do?")
    assert (helped.stop_reason, model.answered) != ("guardrail", 0), helped
    assert "hardship request form" in helped.text, helped.text
    refused, model = await ask("Promise her a payment deferral today so she stops worrying.")
    assert (refused.stop_reason, model.answered) == ("guardrail", 0), refused


async def test_a_skills_scope_does_not_narrow_a_team_guardrail_on_the_same_topic() -> None:
    # Review tick 23: scopes were keyed by topic alone, so the skill's "Not: hardship" narrowed the team's own rule.
    team = Guardrail("gr_team", 1, "Collections rules", (DEFERRAL,), "Collections decides deferrals, not this chat.")
    settings = AgentSettings(
        "ag_advisor", 1, [PromptFragment("You help bankers.")], "m", guardrails=[team], skills=[HARDSHIP_ALWAYS]
    )
    model = Model(lambda m: {"topic": "none"}, ["I'm sorry. The next step is the hardship request form."])
    model.classify = reads_bare_topics_broadly(model)
    req = TurnRequest(
        "t1", "r1", settings, [], user_turn="My client lost her job and cannot make this month's payment."
    )
    events = [
        e async for e in run_turn(req, KernelPorts(model=model.build(), tools=NoTools(), knowledge=NoKnowledge()))
    ]
    last = events[-1]
    assert isinstance(last, TurnFinished)
    result = last.result
    assert (result.stop_reason, model.answered) == ("guardrail", 0), result
    assert result.guardrail is not None and result.guardrail["guardrailId"] == "gr_team", result.guardrail
