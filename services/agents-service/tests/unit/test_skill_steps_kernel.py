"""Skills with steps in the kernel, by failure mode: a saved agent with a plain skill getting a different prompt or
different model settings; a step advancing on a failed rule check, a repeated or cached read skipping its check, a
way past a failed check, or the position lost between replies; skills stacking, or a sub-skill not returning to its
step; an approval pause moving the step, a denial leaving the skill running, personal data kept raw in the record, or
a republished pin changing a skill part-way through; a judge that cannot say no, a judge's failure passing the check,
the answering model overriding the judge, the judge run on a rule, and the judge's tokens left out of the turn's usage.

What these tests ask of the kernel beyond the names the design fixes: `Skill.program` is a
`ops_agent_kernel.steps.SkillProgram` validated from the stored keys (`steps`, `exit`, `returns`, with `ifNot` on a
step); a step's `use` names a skill by its skill id; every running-skill record is one the kernel itself returned on
`TurnResult.run` or `Interrupt.run`, handed back as `TurnRequest.carried_run`."""

from __future__ import annotations

import importlib
import json
from collections.abc import AsyncIterator, Callable
from dataclasses import replace
from typing import Any

import pytest
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models import Model
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel

from ops_agent_kernel import judge
from ops_agent_kernel.context import PLATFORM_RULES
from ops_agent_kernel.events import TurnFinished
from ops_agent_kernel.kernel import run_turn
from ops_agent_kernel.ports import KernelPorts, ToolOutcome
from ops_agent_kernel.tool_cache import ToolCache
from ops_agent_kernel.types import (
    AgentSettings,
    Guardrail,
    PromptFragment,
    Resume,
    Skill,
    ToolGrant,
    TurnRequest,
    TurnResult,
)
from ops_agents.activities.catalog import load_catalog
from ops_agents.api.agent_registry import definition_of
from tests.conftest import SEED
from tests.wire_model import on_wire

Call = tuple[str, dict[str, Any]]
Action = str | Call | list[Call]


def _last_user(messages: list[ModelMessage]) -> str:
    for m in reversed(messages):
        if isinstance(m, ModelRequest):
            for p in m.parts:
                if isinstance(p, UserPromptPart) and isinstance(p.content, str):
                    return p.content
    return ""


class Script:
    """Each answering request takes the next action: a sentence to say, one tool call, or several calls in one step.
    Records what each answering request was sent: its instructions, the tools offered, its model settings, and what
    the calls before it returned. Classification calls answer `classify(message)`; judge calls answer `judge(prompt)`
    ("yes", "no" or "raise") and are kept in `judged`."""

    def __init__(self, *actions: Action, classify: Callable[[str], str] = lambda m: "none", judge: str = "yes") -> None:
        self.actions, self.classify, self.judge = list(actions), classify, judge
        self.instructions: list[str] = []
        self.offered: list[list[str]] = []
        self.settings: list[Any] = []
        self.returned: list[Any] = []
        self.judged: list[str] = []

    def respond(self, messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        prompt = _last_user(messages)
        if prompt.startswith(judge.PROMPT_HEAD):
            self.judged.append(f"{info.instructions}\n{prompt}")
            if self.judge == "raise":
                raise RuntimeError("judge provider down")
            said = {"passed": self.judge == "yes", "reason": f"The judge says {self.judge}."}
            return ModelResponse(parts=[ToolCallPart("final_result", said)])
        if prompt.startswith("Blocked topics:"):
            return ModelResponse(
                parts=[ToolCallPart("final_result", {"topic": self.classify(prompt.split("Message:\n", 1)[1])})]
            )
        self.instructions.append(str(info.instructions or ""))
        self.offered.append([t.name for t in info.function_tools])
        self.settings.append(info.model_settings)
        last = messages[-1]
        if isinstance(last, ModelRequest):
            self.returned += [p.content for p in last.parts if isinstance(p, ToolReturnPart)]
        action: Action = self.actions.pop(0) if self.actions else "Done."
        if isinstance(action, str):
            return ModelResponse(parts=[TextPart(action)])
        calls = action if isinstance(action, list) else [action]
        step = len(self.instructions)
        return ModelResponse(
            parts=[ToolCallPart(name, args, tool_call_id=f"c{step}_{i}") for i, (name, args) in enumerate(calls)]
        )

    def build(self) -> Model:
        async def stream(
            messages: list[ModelMessage], info: AgentInfo
        ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
            for i, part in enumerate(self.respond(messages, info).parts):
                if isinstance(part, TextPart):
                    yield part.content
                elif isinstance(part, ToolCallPart):
                    yield {
                        i: DeltaToolCall(
                            name=part.tool_name, json_args=part.args_as_json_str(), tool_call_id=part.tool_call_id
                        )
                    }

        return on_wire(FunctionModel(self.respond, stream_function=stream))


class Systems:
    """The systems behind the tools: each tool answers its fixed output, or what its function makes of the input."""

    def __init__(self, **answers: Any) -> None:
        self.answers, self.calls = answers, list[Call]()

    async def execute(
        self, tool: str, arguments: dict[str, Any], *, key: str, approval_token: str | None
    ) -> ToolOutcome:
        self.calls.append((tool, arguments))
        answer = self.answers[tool]
        return ToolOutcome(True, answer(arguments) if callable(answer) else answer)


class NoKnowledge:
    async def search(self, query: str, kb_ids: list[str]) -> list[Any]:
        return []


class OneChat:
    """One conversation's kept reads, as every reply of that chat gets them."""

    def __init__(self) -> None:
        self.cache = ToolCache()

    async def current(self) -> ToolCache | None:
        return self.cache


async def reply(
    req: TurnRequest, model: Script, systems: Systems | None = None, chat: OneChat | None = None
) -> tuple[TurnResult, list[Any]]:
    ports = KernelPorts(model=model.build(), tools=systems or Systems(), knowledge=NoKnowledge(), tool_caches=chat)
    events: list[Any] = [e async for e in run_turn(req, ports)]
    last = events[-1]
    assert isinstance(last, TurnFinished), last
    return last.result, events


def program(*steps: dict[str, Any], **rest: Any) -> Any:
    """A skill's step program, from the keys a skill version stores."""
    models: Any = importlib.import_module("ops_agent_kernel.steps")
    return models.SkillProgram.model_validate({"steps": list(steps), **rest})


def stepped(skill_id: str, version: int, name: str, slug: str, steps: Any, *, rules: str = "") -> Skill:
    plain = Skill(skill_id, version, name, slug, f"Use to {name.lower()}.", "on_match", rules)
    return replace(plain, program=steps)


def carrying(req: TurnRequest, run: Any) -> TurnRequest:
    """The next reply of the conversation: it carries the record the reply before it returned."""
    return replace(req, carried_run=run)


def run_of(holder: Any) -> Any:
    """The running-skill record on a turn's result or on its interrupt."""
    return holder.run


def ended(run: Any) -> list[tuple[str, str, int]]:
    return [(h.skill_id, h.ended, h.at_step) for h in run.history]


def agent(skills: list[Skill], **more: Any) -> AgentSettings:
    return replace(
        AgentSettings("ag_disputes", 1, [PromptFragment("You help the disputes desk.")], "m", skills=skills), **more
    )


def tool(name: str, access: Any = "read", *, approval: bool = False) -> ToolGrant:
    schema: dict[str, Any] = {"type": "object", "properties": {"chargeId": {"type": "string"}}}
    return ToolGrant(name, "bank", f"Runs {name}.", access, schema, requires_approval=approval)


# --- a saved agent with a plain skill ---

LEGACY_SPEC: dict[str, Any] = {
    "name": "Branch Concierge",
    "role": "Answers branch staff",
    "instructions": "You help branch staff.\n\nKeep answers to three lines.",
    "skillPins": [
        {
            "skillId": "sk_1",
            "version": 1,
            "name": "Hardship request triage",
            "slug": "hardship-request-triage",
            "useWhen": "The customer cannot pay because of a hardship.",
            "loading": "on_match",
            "instructions": "Steps: record the reason, offer the hardship form.",
            "guardrails": ["payment deferral promise"],
            "tokens": 40,
        }
    ],
}
# What the model is sent for LEGACY_SPEC by the code that predates steps: its instructions, the platform rules, then
# the index of skills to load, and nothing after it.
LEGACY_PROMPT = "\n\n".join(
    [
        "You help branch staff.\n\nKeep answers to three lines.",
        PLATFORM_RULES,
        "## Skills you can load\n\nWhen a request matches one of these, call load_skill with its slug before "
        "answering, then follow what it returns.\n"
        "- hardship-request-triage: The customer cannot pay because of a hardship.",
    ]
)


async def test_a_saved_agent_with_a_plain_skill_gets_the_prompt_and_model_settings_it_had() -> None:
    settings = load_catalog(SEED).settings_for(definition_of("ag_branch", 3, LEGACY_SPEC), "m")
    model = Script("The branch opens at nine.")
    result, _ = await reply(TurnRequest("t1", "th1", settings, [], user_turn="When does the branch open?"), model)
    assert result.stop_reason == "final", result
    assert model.instructions[0] == LEGACY_PROMPT
    offered = set(model.offered[0])
    assert "load_skill" in offered and not offered & {"step_done", "exit", "switch_skill"}, offered
    # No temperature was set, so no model setting is sent: a thinking or parallel-calls default would show here.
    assert model.settings == [None]


# --- a rule check, the ways past it, and the position between replies ---

LOOKUP, REFUND, NOTE = tool("lookup_charge"), tool("refund_charge", "write"), tool("add_note", "write")


def refund_a_charge() -> Skill:
    steps = program(
        {
            "do": "Look up the charge.",
            "use": {"kind": "tool", "id": "lookup_charge"},
            "check": {"text": "result.amount <= 500", "by": "rule"},
            "ifNot": {"action": "retry", "retries": 1},
        },
        {"do": "Tell the person the amount and ask them to confirm."},
        {"do": "Refund the charge.", "use": {"kind": "tool", "id": "refund_charge"}},
    )
    return stepped("sk_refund", 1, "Refund a charge", "refund-a-charge", steps)


NO_ADVICE = Guardrail("gr_advice", 1, "No investment advice", ("investment advice",), "I can't give advice.")


def _amount(arguments: dict[str, Any]) -> dict[str, Any]:
    return {"chargeId": arguments["chargeId"], "amount": 200 if arguments["chargeId"] == "CH-2" else 900}


def _advice(message: str) -> str:
    return "investment advice" if "shares" in message else "none"


async def test_a_failed_rule_check_holds_the_step_through_repeats_cached_reads_and_later_replies() -> None:
    settings = agent([refund_a_charge()], guardrails=[NO_ADVICE], max_tool_calls=None, max_steps=12)
    systems, chat = Systems(lookup_charge=_amount), OneChat()
    ask = TurnRequest("t1", "th1", settings, [LOOKUP, REFUND, NOTE], user_turn="Refund charge CH-1.")
    start: Call = ("switch_skill", {"slug": "refund-a-charge"})

    first = Script(
        start,
        ("exit", {"name": "done"}),
        # Two calls of the step's tool in one model step: one failed attempt, not two.
        [("lookup_charge", {"chargeId": "CH-1"}), ("lookup_charge", {"chargeId": "CH-9"})],
        # The same call again in this reply is not sent to the bank; its saved result fails the check again.
        ("lookup_charge", {"chargeId": "CH-1"}),
        "I could not refund CH-1.",
    )
    one, _ = await reply(ask, first, systems, chat)
    on_step_one = first.instructions[1]
    assert "# Now: Refund a charge, step 1 of 3" in on_step_one, on_step_one
    assert "do not judge it yourself" in on_step_one, "a rule check is never the model's to confirm"
    assert "lookup_charge" in first.offered[1], first.offered[1]
    assert "refund_charge" not in first.offered[1], "a later step's tool waits for its own step"
    assert "add_note" in first.offered[0], "a tool no step names is offered as before"
    assert "Look up the charge." in json.dumps(first.returned[1]), "exit as done on step 1 is refused with the step"
    assert "step 1 of 3" in first.instructions[2] and "step 1 of 3" in first.instructions[3], first.instructions
    assert [c for c, _ in systems.calls] == ["lookup_charge", "lookup_charge"], systems.calls
    assert run_of(one).running is None, "one retry, then the skill ends as failed"
    assert ended(run_of(one)) == [("sk_refund", "failed", 1)]

    second = Script(
        start,
        # Read earlier in this chat: answered from the chat's kept reads, and checked like any result.
        ("lookup_charge", {"chargeId": "CH-1"}),
        ("lookup_charge", {"chargeId": "CH-2"}),
        "CH-2 is 200. Shall I refund it?",
    )
    again = replace(carrying(ask, run_of(one)), turn_id="t2", user_turn="Try CH-2 then.")
    two, _ = await reply(again, second, systems, chat)
    assert "refund_charge" not in second.offered[0], "a failed skill's tools stay withheld until it starts again"
    assert len(systems.calls) == 3, systems.calls
    assert "step 1 of 3" in second.instructions[2], "the cached read failed the same check"
    assert "# Now: Refund a charge, step 2 of 3" in second.instructions[3], second.instructions[3]
    assert "refund_charge" not in second.offered[3]
    running = run_of(two).running
    assert (running.skill_id, running.step, running.results["1"].passed) == ("sk_refund", 2, True), running

    blocked = replace(carrying(ask, run_of(two)), turn_id="t3", user_turn="Should she buy Harbor shares?")
    three, _ = await reply(blocked, Script(classify=_advice), systems, chat)
    assert three.stop_reason == "guardrail", three
    assert run_of(three).running.step == 2, "a reply a guardrail ended keeps the position"

    fourth = Script("Shall I refund CH-2?")
    unclear = replace(carrying(ask, run_of(three)), turn_id="t4", user_turn="Sorry?")
    four, _ = await reply(unclear, fourth, systems, chat)
    assert "# Now: Refund a charge, step 2 of 3" in fourth.instructions[0], fourth.instructions[0]
    assert run_of(four).running.step == 2


# --- switching, and a sub-skill ---

DISCLOSURE = Skill("sk_always", 1, "Bank disclosure", "bank-disclosure", "", "always", "End with: member CDIC.")
HARDSHIP = Skill("sk_hardship", 1, "Hardship triage", "hardship-triage", "Cannot pay.", "on_match", "Offer the form.")
FEES = Skill("sk_fees", 1, "Fee waiver", "fee-waiver", "Asks about a fee.", "on_match", "Waive once a year.")


def close_an_account() -> list[Skill]:
    """A skill whose first step runs the identity skill, and that skill."""
    verify = program({"do": "Ask for the date of birth."}, returns=[{"name": "verified", "type": "yes_no"}])
    close = program(
        {
            "do": "Verify the person.",
            "use": {"kind": "skill", "id": "sk_verify"},
            "check": {"text": "result.verified is true", "by": "rule"},
            "ifNot": {"action": "exit", "exit": "escalate"},
        },
        {"do": "Close the account."},
        exit={"escalate": "Hand the request to a person."},
    )
    return [
        stepped("sk_close", 1, "Close an account", "close-an-account", close),
        stepped("sk_verify", 1, "Verify identity", "verify-identity", verify),
    ]


async def test_one_skill_runs_at_a_time_and_a_sub_skill_returns_to_its_step() -> None:
    # A plain skill carried from an earlier reply is replaced by the next one loaded; always-on skills stay.
    carried: list[dict[str, Any]] = [
        {"skillId": "sk_hardship", "version": 1, "name": HARDSHIP.name, "matched": "cannot pay"}
    ]
    plain = TurnRequest(
        "t1", "th1", agent([DISCLOSURE, HARDSHIP, FEES]), [], user_turn="Waive the fee?", carried_skills=carried
    )
    loaded, _ = await reply(plain, Script(("load_skill", {"slug": "fee-waiver", "matched": "fee"}), "Waived."))
    assert [s["skillId"] for s in loaded.skills] == ["sk_always", "sk_fees"], loaded.skills

    dispute = program({"do": "Ask which charge."}, {"do": "Open the dispute."})
    two = [
        stepped("sk_open", 1, "Open a dispute", "open-a-dispute", dispute),
        stepped("sk_card", 1, "Close a card", "close-a-card", program({"do": "Confirm the card."})),
    ]
    ask = TurnRequest("t1", "th2", agent(two), [], user_turn="I want to dispute a charge.")
    model = Script(
        ("switch_skill", {"slug": "open-a-dispute"}), ("switch_skill", {"slug": "close-a-card"}), "Which card?"
    )
    switched, _ = await reply(ask, model)
    assert "# Now: Open a dispute, step 1 of 2" in model.instructions[1], model.instructions[1]
    assert "# Now: Close a card, step 1 of 1" in model.instructions[2], model.instructions[2]
    assert "Open a dispute, step" not in model.instructions[2], "the skill switched away from left the prompt"
    run = run_of(switched)
    assert (run.running.skill_id, run.running.step, run.running.started_by, run.running.sub) == (
        "sk_card",
        1,
        "model",
        None,
    )
    assert ended(run) == [("sk_open", "switched", 1)]

    # The model loads an on-match skill that has steps: it starts at step 1 as a menu pick does, and its text is
    # never handed over whole. The next reply goes on from the record.
    refund = TurnRequest(
        "t1",
        "th4",
        agent([refund_a_charge(), FEES], max_tool_calls=None),
        [LOOKUP, REFUND, NOTE],
        user_turn="Refund it.",
    )
    model = Script(("load_skill", {"slug": "refund-a-charge", "matched": "refund"}), "Which charge?")
    begun, events = await reply(refund, model)
    index = model.instructions[0]
    assert "is available only as that step" in index, "the index states the rule the kernel keeps"
    assert "before calling any tool" not in index, "the order of calls is not left to the model"
    assert "Its steps call: lookup_charge, refund_charge." in index, index
    assert "step 1 of 3" in json.dumps(model.returned[0]), model.returned
    assert "# Now: Refund a charge, step 1 of 3" in model.instructions[1], model.instructions[1]
    assert "lookup_charge" in model.offered[1] and "refund_charge" not in model.offered[1], model.offered[1]
    assert (run_of(begun).running.skill_id, run_of(begun).running.step) == ("sk_refund", 1)
    assert [e.run.running.step for e in events if type(e).__name__ == "SkillRunChanged"][:1] == [1], "the tracker"
    assert [(e.skill_id, e.how) for e in events if type(e).__name__ == "SkillLoaded"] == [("sk_refund", "started")]
    later = Script("Which charge is it?")
    await reply(replace(carrying(refund, run_of(begun)), turn_id="t2", user_turn="The big one."), later)
    assert "# Now: Refund a charge, step 1 of 3" in later.instructions[0], later.instructions[0]
    assert "lookup_charge" in later.offered[0] and "refund_charge" not in later.offered[0], later.offered[0]
    assert "load_skill" not in later.offered[0], "the step's tool is the only way on"

    close = TurnRequest("t1", "th3", agent(close_an_account()), [], user_turn="Close my account.")
    start: Call = ("switch_skill", {"slug": "close-an-account"})
    model = Script(start, ("exit", {"name": "done", "returns": {"verified": True}}), "Closing it now.")
    returned, _ = await reply(close, model)
    inside = model.instructions[1]
    assert "# Now: Verify identity, step 1 of 1" in inside and "inside Close an account" in inside, inside
    assert "# Now: Close an account, step 2 of 2" in model.instructions[2], model.instructions[2]
    running = run_of(returned).running
    assert (running.skill_id, running.step, running.sub) == ("sk_close", 2, None), running
    assert running.results["1"].passed is True
    assert running.results["1"].value == {"exit": "done", "verified": True}, running.results

    # A sub-skill that fails is a failed check on the step that started it: this step's "if not" names an exit.
    failed, _ = await reply(close, Script(start, ("exit", {"name": "failed", "reason": "No date of birth."}), "Sorry."))
    assert run_of(failed).running is None
    assert ("sk_close", "escalate", 1) in ended(run_of(failed)), run_of(failed)


# --- approval, personal data, and a republished pin ---

HOLD = ToolGrant("place_hold", "bank", "Places a hold on a payment.", "write", {"type": "object", "properties": {}})
CUSTOMER = ToolGrant("lookup_customer", "bank", "Reads a customer.", "read", {"type": "object", "properties": {}})
SSN = "123-45-6789"


def _hold(version: int, then: str) -> Skill:
    steps = program(
        {
            "do": "Place the hold.",
            "use": {"kind": "tool", "id": "place_hold"},
            "check": {"text": "result.held is true", "by": "rule"},
        },
        {"do": then},
    )
    return stepped("sk_hold", version, "Hold a payment", "hold-a-payment", steps)


async def test_a_pause_keeps_the_step_a_denial_ends_the_skill_and_the_record_holds_no_raw_personal_data() -> None:
    settings = agent([_hold(1, "Tell the person the hold reference.")])
    start: Call = ("switch_skill", {"slug": "hold-a-payment"})
    systems = Systems(place_hold={"held": True, "reference": "NB-1"})
    ask = TurnRequest("t1", "th1", settings, [HOLD], user_turn="Hold the payment.")
    paused, _ = await reply(ask, Script(start, ("place_hold", {})), systems)
    assert paused.status == "interrupted" and paused.interrupt is not None, paused
    assert run_of(paused.interrupt).running.step == 1 and systems.calls == []

    approved = Script("The hold is placed.")
    resume = TurnRequest("t2", "th1", settings, [HOLD], resume=Resume(paused.interrupt, "approved", approval_token="k"))
    after, _ = await reply(resume, approved, systems)
    assert [c for c, _ in systems.calls] == ["place_hold"]
    assert "# Now: Hold a payment, step 2 of 2" in approved.instructions[0], approved.instructions[0]
    assert run_of(after).running.step == 2

    untouched = Systems(place_hold={"held": True})
    denied, _ = await reply(
        replace(resume, resume=Resume(paused.interrupt, "rejected", reason="Not this payment.")),
        Script("I did not place the hold."),
        untouched,
    )
    assert untouched.calls == [] and run_of(denied).running is None, run_of(denied)
    assert ended(run_of(denied)) == [("sk_hold", "failed", 1)]

    # A turn paused before skills had steps holds no record: it resumes as a turn with no skill running.
    old = replace(resume, resume=Resume(replace(paused.interrupt, run=None), "approved", approval_token="k"))
    plain, _ = await reply(old, Script("The hold is placed."), Systems(place_hold={"held": True}))
    assert plain.status == "completed", plain
    assert run_of(plain) is None or run_of(plain).running is None

    # The agent is republished with a newer version of the skill: the one running finishes on the version it started.
    newer = agent([_hold(2, "Email the customer the hold reference.")])
    model = Script(("step_done", {}), start, "Starting again.")
    later, _ = await reply(
        replace(carrying(ask, run_of(after)), turn_id="t3", settings=newer, user_turn="And then?"), model, systems
    )
    assert "Tell the person the hold reference." in model.instructions[0], model.instructions[0]
    assert "Email the customer" not in model.instructions[0]
    assert (run_of(later).running.version, run_of(later).running.step) == (2, 1), "the next start uses the new pin"

    # With masking on, the rule reads the real value once as it arrives; the record and its events hold masked text.
    lookup = stepped(
        "sk_lookup",
        1,
        "Check a customer",
        "check-a-customer",
        program(
            {
                "do": "Look up the customer.",
                "use": {"kind": "tool", "id": "lookup_customer"},
                "check": {"text": f'result.ssn == "{SSN}"', "by": "rule"},
            },
            {"do": "Say what you found."},
        ),
    )
    masked = TurnRequest("t1", "th2", agent([lookup], redact_pii=True), [CUSTOMER], user_turn="Check Ann Lee.")
    systems = Systems(lookup_customer={"name": "Ann Lee", "ssn": SSN})
    found, events = await reply(
        masked, Script(("switch_skill", {"slug": "check-a-customer"}), ("lookup_customer", {}), "Found her."), systems
    )
    assert run_of(found).running.step == 2, "the check passed on the unmasked result"
    assert SSN not in run_of(found).model_dump_json()
    changes = [e for e in events if type(e).__name__ == "SkillRunChanged"]
    assert changes and all(SSN not in repr(e) for e in changes), changes


# --- a skill's write is reached only through its step, and an ending the kernel made is final for the reply ---

PAYMENTS = tool("agent__ag_payments")
GATED_REFUND = tool("refund_charge", "write", approval=True)


def refund_after_a_check() -> Skill:
    """A lookup whose rule ends the skill as blocked, then the write, then a hand-off to another agent."""
    steps = program(
        {
            "do": "Look up the charge.",
            "use": {"kind": "tool", "id": "lookup_charge"},
            "check": {"text": "result.amount <= 500", "by": "rule"},
            "ifNot": {"action": "exit", "exit": "blocked"},
        },
        {"do": "Refund the charge.", "use": {"kind": "tool", "id": "refund_charge"}},
        {"do": "Tell payments.", "use": {"kind": "agent", "id": "ag_payments"}},
        exit={"blocked": "The charge is over the refund limit."},
    )
    return stepped("sk_refund", 1, "Refund a charge", "refund-a-charge", steps)


START: Call = ("switch_skill", {"slug": "refund-a-charge"})
PASSES: Call = ("lookup_charge", {"chargeId": "CH-2"})
WRITE: Call = ("refund_charge", {"chargeId": "CH-2"})

# One row per way a model reaches for the write without its step: what it does, and the tools granted.
REACHES: dict[str, tuple[list[Action], list[ToolGrant]]] = {
    "with no skill running": ([WRITE], [LOOKUP, REFUND, NOTE, PAYMENTS]),
    "another agent, with no skill running": ([("agent__ag_payments", {})], [LOOKUP, REFUND, NOTE, PAYMENTS]),
    "in the model step that starts the skill": ([[START, WRITE]], [LOOKUP, REFUND, NOTE, PAYMENTS]),
    "in the model step that leaves the skill": (
        [START, PASSES, [("exit", {"name": "failed"}), WRITE]],
        [LOOKUP, REFUND, NOTE, PAYMENTS],
    ),
    "a write that waits for approval, in the model step that leaves the skill": (
        [START, PASSES, [("exit", {"name": "failed"}), WRITE]],
        [LOOKUP, GATED_REFUND, NOTE, PAYMENTS],
    ),
}


@pytest.mark.parametrize("reach", REACHES, ids=str)
async def test_a_skills_write_runs_only_as_its_step(reach: str) -> None:
    actions, tools = REACHES[reach]
    systems = Systems(lookup_charge=_amount, refund_charge={"refunded": True}, **{"agent__ag_payments": {"ok": True}})
    settings = agent([refund_after_a_check()], max_tool_calls=None, max_steps=12)
    model = Script(*actions, ("search_tools", {"query": "refund"}), "I could not refund it.")
    ask = TurnRequest("t1", "th1", settings, tools, user_turn="Refund CH-2.")
    result, _ = await reply(ask, model, systems)
    assert result.status == "completed", f"a refused call must not wait for a person: {result.status}"
    assert [c for c, _ in systems.calls if c != "lookup_charge"] == [], systems.calls
    first = set(model.offered[0])
    assert not first & {"refund_charge", "agent__ag_payments"}, "a skill's write is not offered before its step"
    assert {"lookup_charge", "add_note"} <= first, "a read, and a write no step runs, stay free"
    assert "refund_charge" not in json.dumps(model.returned[-1]), "search names no tool that waits for its step"


async def test_a_check_that_ends_a_skill_is_final_for_the_reply_and_the_record_says_why() -> None:
    settings = agent([refund_after_a_check()], max_tool_calls=None, max_steps=12)
    systems = Systems(lookup_charge=_amount, refund_charge={"refunded": True})
    ask = TurnRequest("t1", "th1", settings, [LOOKUP, REFUND], user_turn="Refund CH-1.")
    over: Call = ("lookup_charge", {"chargeId": "CH-1"})
    model = Script(START, over, START, ("lookup_charge", {"chargeId": "CH-3"}), "CH-1 is over the limit.")
    one, _ = await reply(ask, model, systems)
    assert ended(run_of(one)) == [("sk_refund", "blocked", 1)], "the skill ended once, as its if-not says"
    assert systems.calls == [over], "the ended skill's tools wait for the next reply, its lookup included"
    told, again = json.dumps(model.returned[1]), json.dumps(model.returned[2])
    assert "result.amount <= 500" in told and "The charge is over the refund limit." in told, told
    assert "cannot start again in this reply" in again, again
    last = run_of(one).history[-1]
    assert (last.why, last.check, last.meaning, last.in_reply) == (
        "check",
        "result.amount <= 500",
        "The charge is over the refund limit.",
        True,
    ), last

    # The next reply may start it again, and the record no longer marks the ending as this reply's.
    second = Script(START, PASSES, "Shall I refund CH-2?")
    two, _ = await reply(replace(carrying(ask, run_of(one)), turn_id="t2", user_turn="CH-2 then."), second, systems)
    assert run_of(two).running.step == 2, run_of(two)
    assert [h.in_reply for h in run_of(two).history] == [False]


async def test_an_ending_stays_final_however_many_skills_end_after_it_in_the_reply() -> None:
    """The record keeps a few past endings. One made in this reply is what keeps its skill from starting again, so
    it stays on the record until the reply is over, whatever ends after it."""
    chat = stepped("sk_chat", 1, "Small talk", "small-talk", program({"do": "Say hello."}, {"do": "Say goodbye."}))
    settings = agent([refund_after_a_check(), chat], max_tool_calls=None, max_steps=40)
    systems = Systems(lookup_charge=_amount)
    ask = TurnRequest("t1", "th1", settings, [LOOKUP, REFUND], user_turn="Refund CH-1.")
    over: Call = ("lookup_charge", {"chargeId": "CH-1"})
    aside: list[Action] = [("switch_skill", {"slug": "small-talk"}), ("exit", {"name": "failed"})] * 6
    model = Script(START, over, *aside, START, over, "CH-1 is over the limit.")
    one, _ = await reply(ask, model, systems)
    # A forgotten ending lets the skill start a second time, and its second ending then reads the same on the
    # record. What tells the two apart is how often the model was put on the skill's first step.
    told = json.dumps(model.returned)
    assert told.count("Now on Refund a charge, step 1") == 1, model.returned[-3:]
    assert "cannot start again in this reply" in told, model.returned[-3:]
    assert ("sk_refund", "blocked", 1) in ended(run_of(one)) and len(ended(run_of(one))) == 7, ended(run_of(one))

    # The next reply starts with the usual few, none marked as this reply's.
    later, _ = await reply(replace(carrying(ask, run_of(one)), turn_id="t2", user_turn="Thanks."), Script("Ok."))
    kept = run_of(later).history
    assert len(kept) == 5 and not any(h.in_reply for h in kept), kept


async def test_a_read_a_builder_locked_to_its_step_runs_only_as_that_step() -> None:
    """A read is free of its skill unless the builder locks it: a look-up that shows a person's record may be one
    the agent should only make inside the procedure that checks who is asking."""
    steps = program(
        {"do": "Look up the charge.", "use": {"kind": "tool", "id": "lookup_charge"}, "locked": True},
        {"do": "Say what it shows."},
    )
    skill = stepped("sk_look", 1, "Look up a charge", "look-up-a-charge", steps)
    systems = Systems(lookup_charge=_amount)
    ask = TurnRequest("t1", "th1", agent([skill], max_steps=12), [LOOKUP, NOTE], user_turn="What is CH-2?")
    look: Call = ("lookup_charge", {"chargeId": "CH-2"})
    # A repeat of a refused call is answered from the reply's record, so the free try names another charge.
    free: Call = ("lookup_charge", {"chargeId": "CH-1"})
    model = Script(free, ("switch_skill", {"slug": "look-up-a-charge"}), look, "It is 200.")
    result, _ = await reply(ask, model, systems)
    assert "lookup_charge" not in model.offered[0] and "add_note" in model.offered[0], model.offered[0]
    assert systems.calls == [look], f"refused with no skill running, run once as the step: {model.returned}"
    assert run_of(result).running.step == 2
    # Stored only when on: a step saved without it reads as before.
    assert "locked" not in program({"do": "Look up.", "use": {"kind": "tool", "id": "x"}}).steps[0].model_dump(
        exclude_none=True
    )


async def test_a_workflow_a_step_runs_is_refused_outside_the_skill_and_runs_as_its_step() -> None:
    """A step names a workflow by its id; the service grants it under another spelling. Matched by the wrong one,
    the workflow is free to start with no skill running, and its step never sees it run."""
    steps = program(
        {
            "do": "Close the case.",
            "use": {"kind": "workflow", "id": "wf_close"},
            "check": {"text": 'result.status == "closed"', "by": "rule"},
        },
        {"do": "Say it is closed."},
    )
    skill = stepped("sk_close", 1, "Close a case", "close-a-case", steps)
    close = tool("workflow__wf_close", "workflow")
    systems = Systems(**{"workflow__wf_close": {"status": "closed"}})
    ask = TurnRequest("t1", "th1", agent([skill], max_steps=12), [LOOKUP, close], user_turn="Close case 7.")
    free: Call = ("workflow__wf_close", {"case": "1"})
    start: Call = ("workflow__wf_close", {"case": "7"})
    model = Script(free, ("switch_skill", {"slug": "close-a-case"}), start, "It is closed.")
    result, _ = await reply(ask, model, systems)
    assert "workflow__wf_close" not in model.offered[0], model.offered[0]
    assert systems.calls == [start], f"refused with no skill running, run once as the step: {model.returned}"
    assert run_of(result).running.step == 2, "the step saw its workflow's result and passed its rule"


# --- the judge ---


def judged_refund() -> Skill:
    """A lookup whose check is a sentence the judge decides, then the write, checked by a rule."""
    steps = program(
        {
            "do": "Look up the charge.",
            "use": {"kind": "tool", "id": "lookup_charge"},
            "check": {"text": "The amount is under 500.", "by": "model"},
            "ifNot": {"action": "exit", "exit": "blocked"},
        },
        {
            "do": "Refund the charge.",
            "use": {"kind": "tool", "id": "refund_charge"},
            "check": {"text": "result.refunded is true", "by": "rule"},
        },
        {"do": "Tell the person."},
        exit={"blocked": "The charge is over the refund limit."},
    )
    return stepped("sk_judged", 1, "Judge a charge", "judge-a-charge", steps)


def confirm_by_word() -> Skill:
    steps = program({"do": "Ask for the date of birth.", "check": {"text": "The caller gave a date.", "by": "model"}})
    return stepped("sk_word", 1, "Confirm by word", "confirm-by-word", steps)


JUDGED: Call = ("switch_skill", {"slug": "judge-a-charge"})
BIG: Call = ("lookup_charge", {"chargeId": "CH-1"})
SMALL: Call = ("lookup_charge", {"chargeId": "CH-2"})
REFUND_ONE: Call = ("refund_charge", {"chargeId": "CH-1"})
REFUND_TWO: Call = ("refund_charge", {"chargeId": "CH-2"})

# skill, the model's actions, the judge's answer -> the tools that reached a system, the endings, the step the record
# is on (None once ended), how many judge calls, and words the model is told.
VERDICTS: dict[str, tuple[Callable[[], Skill], list[Action], str, list[str], list[Any], int | None, int, str]] = {
    "the judge says yes: the step moves on to the write": (
        judged_refund,
        [JUDGED, SMALL, REFUND_TWO],
        "yes",
        ["lookup_charge", "refund_charge"],
        [],
        3,
        1,
        "yes.",
    ),
    "the judge says no: the if-not ends the skill and the write is held": (
        judged_refund,
        [JUDGED, BIG, REFUND_ONE],
        "no",
        ["lookup_charge"],
        [("sk_judged", "blocked", 1)],
        None,
        1,
        "The judge says no.",
    ),
    "the judge raises: no verdict fails the step": (
        judged_refund,
        [JUDGED, BIG, REFUND_ONE],
        "raise",
        ["lookup_charge"],
        [("sk_judged", "blocked", 1)],
        None,
        1,
        "no verdict",
    ),
    "the model sends holds true on a judged step: refused": (
        confirm_by_word,
        [("switch_skill", {"slug": "confirm-by-word"}), ("step_done", {"holds": True})],
        "yes",
        [],
        [],
        1,
        0,
        "The judge decides this step",
    ),
    "a rule decides: the judge is never called": (
        refund_after_a_check,
        [START, PASSES],
        "yes",
        ["lookup_charge"],
        [],
        2,
        0,
        "step 2 of 3",
    ),
}


@pytest.mark.parametrize("row", VERDICTS, ids=str)
async def test_a_judge_decides_a_sentence_check_and_its_no_or_silence_fails_the_step(row: str) -> None:
    make, actions, says, reached, endings, on, calls, told = VERDICTS[row]
    systems = Systems(lookup_charge=_amount, refund_charge={"refunded": True})
    model = Script(*actions, "Done.", judge=says)
    ask = TurnRequest(
        "t1", "th9", agent([make()], max_tool_calls=None, max_steps=12), [LOOKUP, REFUND], user_turn="Hi."
    )
    done, _ = await reply(ask, model, systems)
    run = run_of(done)
    assert [c for c, _ in systems.calls] == reached, systems.calls
    assert ended(run) == endings, run.history
    assert (run.running.step if run.running else None) == on, run.running
    assert len(model.judged) == calls, model.judged
    assert told in json.dumps(model.returned), model.returned
    if calls:
        # Given the result as the tool returned it, and none of the agent's instructions.
        assert '"amount": ' in model.judged[0] and "disputes desk" not in model.judged[0], model.judged[0]
    if endings:
        assert [h.tools for h in run.holds] == [["refund_charge"]], run.holds


class Aliases:
    """The models service by alias, recording each request under the alias it ran on, as the call ledger does."""

    def __init__(self, turn: Script) -> None:
        self.turn, self.ran = turn, list[str]()

    def model_for(self, alias: str) -> Any:
        def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            self.ran.append(alias)
            return self.turn.respond(messages, info)

        if alias == "m":
            return self.turn.build()
        return on_wire(FunctionModel(respond))


async def test_a_judged_steps_tokens_are_in_the_turns_usage_under_the_judge_alias() -> None:
    model = Script(JUDGED, SMALL, "Done.")
    source = Aliases(model)
    ports = KernelPorts(
        model=model.build(), tools=Systems(lookup_charge=_amount), knowledge=NoKnowledge(), models=source
    )
    ask = TurnRequest("t1", "th9", agent([judged_refund()], max_tool_calls=None), [LOOKUP, REFUND], user_turn="Hi.")
    last = [e async for e in run_turn(ask, ports)][-1]
    assert isinstance(last, TurnFinished), last
    assert source.ran == [judge.JUDGE_ALIAS], source.ran
    assert last.result.usage.requests == len(model.instructions) + 1, (last.result.usage, len(model.instructions))
