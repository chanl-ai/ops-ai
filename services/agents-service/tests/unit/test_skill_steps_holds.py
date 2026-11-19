"""Skills with steps in the kernel, by failure mode: a failed skill's sub-skill write staying callable; an exit that
stops a skill freeing its later write in the same reply; a skill starting without an input it requires; a rule
comparing a masked input; a step with a tool still offered plan, tool search and plain skills, or tool search naming
a tool a later step holds; and a thinking default reaching a saved agent's model request unseen.

The scripted model, the systems and the skill builders are those of `test_skill_steps_kernel`."""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

from pydantic_ai.messages import ModelMessage, ModelResponse
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.profiles import ModelProfile

from ops_agent_kernel.types import Skill, SkillInput, ToolGrant, TurnRequest
from ops_agents.activities.catalog import load_catalog
from ops_agents.api.agent_registry import definition_of
from tests.conftest import SEED
from tests.unit.test_skill_steps_kernel import (
    HARDSHIP,
    LEGACY_SPEC,
    LOOKUP,
    NOTE,
    REFUND,
    SSN,
    Call,
    Script,
    Systems,
    agent,
    carrying,
    ended,
    program,
    refund_a_charge,
    reply,
    run_of,
    stepped,
    tool,
)


def _amount(arguments: dict[str, Any]) -> dict[str, Any]:
    return {"chargeId": arguments["chargeId"], "amount": 200 if arguments["chargeId"] == "CH-2" else 900}


def pay_out_after_a_check(if_not: dict[str, Any], **rest: Any) -> list[Skill]:
    """A skill whose first step checks the charge and whose second runs the pay-out skill, and that skill: its one
    step calls the refund."""
    check = program(
        {
            "do": "Look up the charge.",
            "use": {"kind": "tool", "id": "lookup_charge"},
            "check": {"text": "result.amount <= 500", "by": "rule"},
            "ifNot": if_not,
        },
        {"do": "Pay it out.", "use": {"kind": "skill", "id": "sk_pay"}},
        **rest,
    )
    pay = program({"do": "Refund the charge.", "use": {"kind": "tool", "id": "refund_charge"}})
    return [
        stepped("sk_check", 1, "Check then pay", "check-then-pay", check),
        stepped("sk_pay", 1, "Pay out", "pay-out", pay),
    ]


async def test_a_failed_skill_holds_the_write_of_the_sub_skill_it_never_reached() -> None:
    skills = pay_out_after_a_check({"action": "retry", "retries": 0})
    ask = TurnRequest("t1", "th1", agent(skills, max_steps=12), [LOOKUP, REFUND, NOTE], user_turn="Refund CH-1.")
    systems = Systems(lookup_charge=_amount, refund_charge={"refunded": True})
    model = Script(
        ("switch_skill", {"slug": "check-then-pay"}),
        ("lookup_charge", {"chargeId": "CH-1"}),
        ("refund_charge", {"chargeId": "CH-1"}),
        "I could not refund CH-1.",
    )
    result, _ = await reply(ask, model, systems)
    assert ended(run_of(result)) == [("sk_check", "failed", 1)]
    assert "refund_charge" not in model.offered[2], "the sub-skill's write is held after its parent failed"
    assert "add_note" in model.offered[2], "a tool no step names is offered as before"
    assert [c for c, _ in systems.calls] == ["lookup_charge"], systems.calls

    # The next reply starts the pay-out skill directly: its step names the refund, which the failed skill holds.
    later = Script(
        ("switch_skill", {"slug": "pay-out"}), ("refund_charge", {"chargeId": "CH-1"}), "Nothing was refunded."
    )
    two, _ = await reply(replace(carrying(ask, run_of(result)), turn_id="t2", user_turn="Pay it out."), later, systems)
    assert all("refund_charge" not in offered for offered in later.offered), later.offered
    assert [c for c, _ in systems.calls] == ["lookup_charge"], systems.calls
    # It does not stay running on a step whose tool it cannot be offered: it ends, and the model is told why.
    assert run_of(two).running is None, run_of(two)
    why = "refund_charge is held because check-then-pay failed its check; start check-then-pay again."
    assert why in json.dumps(later.returned[0]), later.returned

    # The failed skill starts again and its check passes: the write is its own to call.
    again = Script(
        ("switch_skill", {"slug": "check-then-pay"}),
        ("lookup_charge", {"chargeId": "CH-2"}),
        ("refund_charge", {"chargeId": "CH-2"}),
        "CH-2 is refunded.",
    )
    three, _ = await reply(replace(carrying(ask, run_of(two)), turn_id="t3", user_turn="Refund CH-2."), again, systems)
    assert [c for c, _ in systems.calls][1:] == ["lookup_charge", "refund_charge"], systems.calls
    # Having passed the steps that held them, it holds nothing: the pay-out skill runs on its own again.
    after = Script(("switch_skill", {"slug": "pay-out"}), ("refund_charge", {"chargeId": "CH-2"}), "Refunded again.")
    await reply(replace(carrying(ask, run_of(three)), turn_id="t4", user_turn="Once more."), after, systems)
    assert [c for c, _ in systems.calls][3:] == ["refund_charge"], systems.calls

    # A conversation where nothing failed holds nothing: the pay-out skill runs on its own.
    fresh = Systems(lookup_charge=_amount, refund_charge={"refunded": True})
    alone = Script(("switch_skill", {"slug": "pay-out"}), ("refund_charge", {"chargeId": "CH-1"}), "CH-1 is refunded.")
    await reply(ask, alone, fresh)
    assert [c for c, _ in fresh.calls] == ["refund_charge"], fresh.calls

    # Two failed skills hold the refund. Each, started again, is re-proving its own check, so the other's hold does
    # not stop it: the tool is never locked for the whole conversation.
    both = Systems(lookup_charge=_amount, refund_charge={"refunded": True})
    gave_up = Script(("switch_skill", {"slug": "pay-out"}), ("exit", {"name": "failed"}), "I stopped.")
    one, _ = await reply(ask, gave_up, both)
    failed = Script(("switch_skill", {"slug": "check-then-pay"}), ("lookup_charge", {"chargeId": "CH-1"}), "No.")
    held, _ = await reply(replace(carrying(ask, run_of(one)), turn_id="t2", user_turn="Refund CH-1."), failed, both)
    assert set(run_of(held).held_by_failed) == {"sk_pay", "sk_check"}, run_of(held)
    retry = Script(("switch_skill", {"slug": "pay-out"}), ("refund_charge", {"chargeId": "CH-2"}), "CH-2 is refunded.")
    await reply(replace(carrying(ask, run_of(held)), turn_id="t3", user_turn="Pay out CH-2."), retry, both)
    assert [c for c, _ in both.calls] == ["lookup_charge", "refund_charge"], both.calls


async def test_a_failed_skill_still_holds_its_write_after_more_skills_ended_than_the_record_lists() -> None:
    skills = pay_out_after_a_check({"action": "retry", "retries": 0})
    ask = TurnRequest("t1", "th1", agent(skills, max_steps=12), [LOOKUP, REFUND, NOTE], user_turn="Refund CH-1.")
    systems = Systems(lookup_charge=_amount, refund_charge={"refunded": True})
    failing = Script(("switch_skill", {"slug": "check-then-pay"}), ("lookup_charge", {"chargeId": "CH-1"}), "No.")
    result, _ = await reply(ask, failing, systems)
    run = run_of(result)
    # Six later replies each start the pay-out skill and try the refund; each ending is one more entry in the list.
    for n in range(2, 8):
        model = Script(
            ("switch_skill", {"slug": "pay-out"}),
            ("exit", {"name": "failed"}),
            ("refund_charge", {"chargeId": "CH-1"}),
            "Not refunded.",
        )
        result, _ = await reply(replace(carrying(ask, run), turn_id=f"t{n}", user_turn="Pay it out."), model, systems)
        run = run_of(result)
        assert all("refund_charge" not in offered for offered in model.offered), (n, model.offered)
    assert "sk_check" not in [h.skill_id for h in run.history], "the failed skill's entry has left the list"
    assert [c for c, _ in systems.calls] == ["lookup_charge"], systems.calls


async def test_a_step_does_not_start_a_skill_without_an_input_it_requires() -> None:
    check, pay = pay_out_after_a_check({"action": "retry", "retries": 0})
    needs = replace(pay, inputs=(SkillInput("charge_id", required=True), SkillInput("amount", required=True)))
    ask = TurnRequest("t1", "th1", agent([check, needs], max_steps=12), [LOOKUP, REFUND], user_turn="Refund CH-2.")
    systems = Systems(lookup_charge=_amount, refund_charge={"refunded": True})
    # The look-up gives the amount by name and no charge_id, and the skill was started with none to pass on.
    model = Script(
        ("switch_skill", {"slug": "check-then-pay"}),
        ("lookup_charge", {"chargeId": "CH-2"}),
        ("refund_charge", {"chargeId": "CH-2"}),
        "I could not refund CH-2.",
    )
    result, _ = await reply(ask, model, systems)
    assert ended(run_of(result)) == [("sk_check", "failed", 2)], run_of(result)
    assert [c for c, _ in systems.calls] == ["lookup_charge"], systems.calls
    told = model.returned[1]["note"]
    assert "needs charge_id," in told, told

    # Started with the charge: the pay-out skill gets it from its parent, and the amount from the step before.
    start: Call = ("switch_skill", {"slug": "check-then-pay", "inputs": {"charge_id": "CH-2"}})
    given = Script(start, ("lookup_charge", {"chargeId": "CH-2"}), "Shall I refund CH-2?")
    started, _ = await reply(ask, given, systems)
    assert run_of(started).running.sub.inputs == {"charge_id": "CH-2", "amount": "200"}


async def test_an_exit_that_stops_a_skill_holds_its_later_write_for_the_rest_of_the_reply() -> None:
    skills = pay_out_after_a_check(
        {"action": "exit", "exit": "escalate"}, exit={"escalate": "Hand the request to a person."}
    )
    ask = TurnRequest("t1", "th1", agent(skills, max_steps=12), [LOOKUP, REFUND, NOTE], user_turn="Refund CH-1.")
    systems = Systems(lookup_charge=_amount, refund_charge={"refunded": True})
    model = Script(
        ("switch_skill", {"slug": "check-then-pay"}),
        ("lookup_charge", {"chargeId": "CH-1"}),
        # The pay-out skill started directly: its step names the refund, which the stopped skill still holds.
        ("switch_skill", {"slug": "pay-out"}),
        ("refund_charge", {"chargeId": "CH-1"}),
        "A person will look at CH-1.",
    )
    result, _ = await reply(ask, model, systems)
    assert ("sk_check", "escalate", 1) in ended(run_of(result)), run_of(result)
    # The pay-out skill does not sit on a step it cannot do: it ends at once and the model is told why.
    assert run_of(result).running is None, run_of(result)
    why = "refund_charge is held for the rest of this reply because check-then-pay ended as escalate"
    assert why in json.dumps(model.returned[2]), model.returned
    assert all("refund_charge" not in offered for offered in model.offered[2:]), model.offered
    assert [c for c, _ in systems.calls] == ["lookup_charge"], systems.calls


async def test_a_skill_does_not_start_without_an_input_it_requires() -> None:
    needs = replace(refund_a_charge(), inputs=(SkillInput("charge_id", required=True), SkillInput("reason")))
    ask = TurnRequest("t1", "th1", agent([needs], max_steps=12), [LOOKUP, REFUND], user_turn="Refund a charge.")
    start: Call = ("switch_skill", {"slug": "refund-a-charge"})
    model = Script(start, ("switch_skill", {"slug": "refund-a-charge", "inputs": {"charge_id": " "}}), "Which charge?")
    refused, _ = await reply(ask, model)
    assert run_of(refused).running is None, "nothing starts while a required input is missing or blank"
    assert all("charge_id" in json.dumps(r) and "reason" not in json.dumps(r) for r in model.returned), model.returned

    given = Script(("switch_skill", {"slug": "refund-a-charge", "inputs": {"charge_id": "CH-2"}}), "Looking it up.")
    started, _ = await reply(ask, given)
    assert run_of(started).running.inputs == {"charge_id": "CH-2"}

    # Picked from the chat menu without it: not started, and the model is told what to ask for.
    pick: list[dict[str, Any]] = [
        {"skillId": "sk_refund", "version": 1, "name": needs.name, "matched": "Picked", "how": "picked"}
    ]
    picked = Script("Which charge should I refund?")
    menu, _ = await reply(replace(ask, carried_skills=pick), picked)
    assert run_of(menu).running is None
    assert "charge_id" in picked.instructions[0] and "# Now:" not in picked.instructions[0], picked.instructions[0]


async def test_a_skill_whose_first_step_cannot_start_its_skill_says_which_input_is_missing() -> None:
    pay = replace(pay_out_after_a_check({"action": "retry"})[1], inputs=(SkillInput("charge_id", required=True),))
    first = program(
        {"do": "Pay it out.", "use": {"kind": "skill", "id": "sk_pay"}, "ifNot": {"action": "retry", "retries": 0}}
    )
    direct = stepped("sk_direct", 1, "Pay at once", "pay-at-once", first)
    ask = TurnRequest("t1", "th1", agent([direct, pay], max_steps=12), [REFUND], user_turn="Pay it out.")
    model = Script(("switch_skill", {"slug": "pay-at-once"}), "Which charge?")
    result, _ = await reply(ask, model)
    assert ended(run_of(result)) == [("sk_direct", "failed", 1)], run_of(result)
    assert "needs charge_id," in json.dumps(model.returned[0]), model.returned

    # Picked from the chat menu, the same is written into what the model reads.
    pick: list[dict[str, Any]] = [
        {"skillId": "sk_direct", "version": 1, "name": direct.name, "matched": "Picked", "how": "picked"}
    ]
    picked = Script("Which charge?")
    await reply(replace(ask, carried_skills=pick), picked)
    assert "needs charge_id," in picked.instructions[0], picked.instructions[0]


CUSTOMER = ToolGrant("lookup_customer", "bank", "Reads a customer.", "read", {"type": "object", "properties": {}})


async def test_a_rule_that_reads_a_masked_input_fails_with_the_input_named() -> None:
    steps = program(
        {"do": "Confirm who is asking."},
        {
            "do": "Look up the customer.",
            "use": {"kind": "tool", "id": "lookup_customer"},
            # Compared with the masked placeholder, this rule would pass on the customer's own number.
            "check": {"text": "result.ssn != inputs.ssn", "by": "rule"},
        },
        {"do": "Say what you found."},
    )
    skill = stepped("sk_other", 1, "Check another person", "check-another-person", steps)
    settings = agent([skill], redact_pii=True, max_steps=12)
    ask = TurnRequest("t1", "th1", settings, [CUSTOMER], user_turn="Check this number.")
    systems = Systems(lookup_customer={"name": "Ann Lee", "ssn": SSN})
    first = Script(("switch_skill", {"slug": "check-another-person", "inputs": {"ssn": SSN}}), ("step_done", {}), "Ok.")
    one, _ = await reply(ask, first, systems)
    assert run_of(one).running.step == 2 and SSN not in run_of(one).model_dump_json()

    second = Script(("lookup_customer", {}), "I could not check it.")
    two, _ = await reply(replace(carrying(ask, run_of(one)), turn_id="t2", user_turn="Go on."), second, systems)
    running = run_of(two).running
    assert (running.step, running.results["2"].passed) == (2, False), "a placeholder is never compared"
    told = json.dumps(second.returned)
    assert "ssn" in told and "masked" in told, told

    # A record that lost its mark still holds the placeholder: the rule is not run on it either.
    bare = run_of(one).model_copy(deep=True)
    bare.running.masked_inputs = []
    third = Script(("lookup_customer", {}), "I could not check it.")
    three, _ = await reply(replace(carrying(ask, bare), turn_id="t3", user_turn="Go on."), third, systems)
    assert run_of(three).running.results["2"].passed is False, "an unmarked placeholder is never compared"


async def test_a_step_with_a_tool_offers_no_plan_search_or_plain_skill_and_search_names_no_held_tool() -> None:
    settings = agent([refund_a_charge(), HARDSHIP], max_tool_calls=None, max_steps=12)
    ask = TurnRequest("t1", "th1", settings, [LOOKUP, REFUND, NOTE, tool("refund_fee")], user_turn="Refund CH-2.")
    model = Script(
        ("switch_skill", {"slug": "refund-a-charge"}),
        ("lookup_charge", {"chargeId": "CH-2"}),
        ("search_tools", {"query": "refund note"}),
        "CH-2 is 200. Shall I refund it?",
    )
    await reply(ask, model, Systems(lookup_charge=_amount))
    on_lookup = set(model.offered[1])
    assert "lookup_charge" in on_lookup and {"step_done", "exit", "switch_skill"} <= on_lookup, on_lookup
    assert not on_lookup & {"plan", "search_tools", "load_skill"}, on_lookup
    # Step 2 names no tool: search is offered again, and finds the free tools but not the one step 3 holds.
    assert "search_tools" in model.offered[2], model.offered[2]
    found = [t["name"] for t in model.returned[-1]["tools"]]
    assert "refund_fee" in found and "add_note" in found and "refund_charge" not in found, found


class ThinkingScript(Script):
    """A scripted model that takes a thinking setting, and records the one each request resolved to. The library
    drops `thinking` from the settings of a model that does not take it (`Model.prepare_request`), so the plain
    scripted model never sees one."""

    def __init__(self, *actions: Any) -> None:
        super().__init__(*actions)
        self.thinking: list[Any] = []

    def respond(self, messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        self.thinking.append(info.model_request_parameters.thinking)
        return super().respond(messages, info)

    def build(self) -> FunctionModel:
        stream = super().build().stream_function
        assert stream is not None
        return FunctionModel(self.respond, stream_function=stream, profile=ModelProfile(supports_thinking=True))


async def test_a_saved_agent_sends_no_thinking_setting_and_a_set_one_reaches_the_model() -> None:
    settings = load_catalog(SEED).settings_for(definition_of("ag_branch", 3, LEGACY_SPEC), "m")
    ask = TurnRequest("t1", "th1", settings, [], user_turn="When does the branch open?")
    legacy = ThinkingScript("The branch opens at nine.")
    await reply(ask, legacy)
    assert legacy.thinking == [None], "a saved agent with no thinking setting sends none"

    low = ThinkingScript("The branch opens at nine.")
    await reply(replace(ask, settings=replace(settings, thinking="low")), low)
    assert low.thinking == ["low"], "the scripted model sees a thinking setting when one is sent"
