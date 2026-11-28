"""Skills with steps in the kernel, by failure mode: a tool running past a step whose check failed or whose call
was denied (one table of conversations, a row per way round the hold); an exit that stops a skill freeing its later
write in the same reply; a skill starting without an input it requires; a rule comparing a masked input; a step with
a tool still offered plan, tool search and plain skills, or tool search naming a tool a later step holds; and a
thinking default reaching a saved agent's model request unseen.

The scripted model, the systems and the skill builders are those of `test_skill_steps_kernel`."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any

import pytest

from ops_agent_kernel.ports import ToolOutcome
from ops_agent_kernel.testing import Answer
from ops_agent_kernel.types import Resume, Skill, SkillInput, ToolGrant, TurnRequest
from ops_agents.activities.catalog import load_catalog
from ops_agents.api.agent_registry import definition_of
from ops_service_kit.http import Json
from tests.conftest import SEED
from tests.unit.test_skill_steps_kernel import (
    HARDSHIP,
    LEGACY_SPEC,
    LOOKUP,
    NOTE,
    REFUND,
    SSN,
    Action,
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


CHECK: Call = ("switch_skill", {"slug": "check-then-pay"})
PAY: Call = ("switch_skill", {"slug": "pay-out"})
GOODWILL: Call = ("switch_skill", {"slug": "goodwill"})
NOTE_PAY: Call = ("switch_skill", {"slug": "note-then-pay"})
LOOK_PAY_NOTE: Call = ("switch_skill", {"slug": "look-pay-note"})
GATED: Call = ("switch_skill", {"slug": "hold-then-pay"})
RUNS_NEEDY: Call = ("switch_skill", {"slug": "runs-needy"})
HOLD_ONLY: Call = ("switch_skill", {"slug": "hold-only"})
LOOK_NOTE_PAY: Call = ("switch_skill", {"slug": "look-note-pay"})
RUNS_LOOK: Call = ("switch_skill", {"slug": "runs-look"})
CONFIRM_NO: Call = ("switch_skill", {"slug": "confirm-then-pay", "inputs": {"ok": "no"}})
RUNS_SORRY: Call = ("switch_skill", {"slug": "runs-sorry"})
RUNS_LOOK_PAY: Call = ("switch_skill", {"slug": "runs-look-then-pay"})
LOOK_THEN_NOTE: Call = ("switch_skill", {"slug": "look-then-note-pay"})
JUMP_RUNS_NOTE: Call = ("switch_skill", {"slug": "jump-runs-note"})
LETTER_CHECK_PAY: Call = ("switch_skill", {"slug": "letter-check-pay"})
CHECK_JUMP: Call = ("switch_skill", {"slug": "check-jump"})
RUNS_LOOK_RETRY: Call = ("switch_skill", {"slug": "runs-look-retry"})
SKIP_IS_FINE: Call = ("switch_skill", {"slug": "skip-is-fine"})
ESCALATE: Call = ("exit", {"name": "escalate"})
SKIP: Call = ("exit", {"name": "skip"})
SKIP_OK: Call = ("exit", {"name": "skip", "returns": {"ok": True}})
LOOK_THEN_LETTER: Call = ("switch_skill", {"slug": "look-then-letter"})
RUNS_WAIT: Call = ("switch_skill", {"slug": "runs-wait-then-look"})
# The rule on a step that runs the look-ok skill, by the name of the skill that has that step.
PARENT_RULES = {
    "ok_true": "result.ok is true",
    "ok_ne_false": "result.ok != false",
    "ok_not_false": "result.ok is not false",
    "tier": 'inputs.tier == "gold"',
    "names_skip": 'result.exit in ["done", "skip"]',
    "not_failed": 'result.exit != "failed"',
}


def after_skip(key: str) -> Call:
    return ("switch_skill", {"slug": f"rule-{key}", "inputs": {"tier": "gold"}})


ID_CHECK = tool("check_id")
GIVE_UP: Call = ("exit", {"name": "failed"})
DONE: Call = ("step_done", {})
PLACE: Call = ("place_hold", {})
GATE = tool("place_hold", "write", approval=True)


def look(charge: str) -> Call:
    return ("lookup_charge", {"chargeId": charge})


def refund(charge: str) -> Call:
    return ("refund_charge", {"chargeId": charge})


def note(charge: str) -> Call:
    return ("add_note", {"chargeId": charge})


def book(if_not: dict[str, Any], version: int = 1) -> list[Skill]:
    """The skills every thread below has. CH-1 is 900 and fails the look-up rule (500 at most); CH-2 is 200 and
    passes. A note is saved for CH-2 only."""
    check, pay = pay_out_after_a_check(if_not)
    a_tool = {"kind": "tool", "id": "refund_charge"}
    saved = {"text": "result.saved is true", "by": "rule"}
    small = {"text": "result.amount <= 500", "by": "rule"}
    once = {"action": "retry", "retries": 0}
    noted = {"do": "Note it.", "use": {"kind": "tool", "id": "add_note"}, "check": saved, "ifNot": once}
    looked = {"do": "Look it up.", "use": {"kind": "tool", "id": "lookup_charge"}, "check": small, "ifNot": once}
    paid = {"do": "Refund it.", "use": a_tool}
    letter = {"do": "Send the letter.", "use": {"kind": "tool", "id": "add_note"}}
    needy = stepped("sk_needy", 1, "Needy", "needy", program(paid))
    return [
        replace(check, version=version),
        pay,
        stepped("sk_goodwill", 1, "Goodwill", "goodwill", program({"do": "Say sorry."}, paid)),
        stepped("sk_note_pay", 1, "Note then pay", "note-then-pay", program(noted, paid)),
        stepped(
            "sk_look_pay_note",
            1,
            "Look pay note",
            "look-pay-note",
            program(looked, paid, {"do": "Note it.", "use": {"kind": "tool", "id": "add_note"}}),
        ),
        stepped(
            "sk_gated",
            1,
            "Hold then pay",
            "hold-then-pay",
            program({"do": "Place the hold.", "use": {"kind": "tool", "id": "place_hold"}}, paid),
        ),
        replace(needy, inputs=(SkillInput("charge_id", required=True),)),
        stepped(
            "sk_runs_needy",
            1,
            "Runs needy",
            "runs-needy",
            program(
                {"do": "Pay.", "use": {"kind": "skill", "id": "sk_needy"}, "ifNot": once},
                {"do": "Note it.", "use": {"kind": "tool", "id": "add_note"}},
            ),
        ),
        stepped(
            "sk_hold_only",
            1,
            "Hold only",
            "hold-only",
            program({"do": "Place the hold.", "use": {"kind": "tool", "id": "place_hold"}}),
        ),
        stepped(
            "sk_look_note_pay",
            1,
            "Look note pay",
            "look-note-pay",
            program({**looked, "ifNot": {"action": "goto", "step": 2}}, noted, paid),
        ),
        stepped(
            "sk_runs_look",
            1,
            "Runs look",
            "runs-look",
            program({"do": "Look and pay.", "use": {"kind": "skill", "id": "sk_look_pay_note"}, "ifNot": once}),
        ),
        stepped(
            "sk_confirm",
            1,
            "Confirm then pay",
            "confirm-then-pay",
            program({"do": "Confirm.", "check": {"text": "inputs.ok == 'yes'", "by": "rule"}, "ifNot": once}, paid),
        ),
        stepped(
            "sk_sorry", 1, "Sorry", "sorry", program({"do": "Say sorry."}, exit={"escalate": "Hand it to a person."})
        ),
        stepped(
            "sk_runs_sorry",
            1,
            "Runs sorry",
            "runs-sorry",
            program(
                {
                    "do": "Say sorry.",
                    "use": {"kind": "skill", "id": "sk_sorry"},
                    "check": {"text": "result.ok is true", "by": "rule"},
                    "ifNot": once,
                },
                {"do": "Note it.", "use": {"kind": "tool", "id": "add_note"}},
            ),
        ),
        stepped("sk_look_then_letter", 1, "Look then letter", "look-then-letter", program(looked, letter)),
        stepped(
            "sk_wait_then_note",
            1,
            "Wait then note",
            "wait-then-note",
            program({"do": "Wait."}, letter, exit={"skip": "Go on without the note."}),
        ),
        stepped(
            "sk_runs_wait",
            1,
            "Runs wait then look",
            "runs-wait-then-look",
            program(
                {
                    "do": "Note it.",
                    "use": {"kind": "skill", "id": "sk_wait_then_note"},
                    "check": {"text": 'result.exit == "done"', "by": "rule"},
                    "ifNot": once,
                },
                {"do": "Look it up.", "use": {"kind": "tool", "id": "lookup_charge"}},
            ),
        ),
        stepped(
            "sk_look_or_escalate",
            1,
            "Look or escalate",
            "look-or-escalate",
            program({**looked, "ifNot": {"action": "retry", "retries": 1}}, exit={"escalate": "Hand it to a person."}),
        ),
        stepped(
            "sk_runs_look_pay",
            1,
            "Runs look then pay",
            "runs-look-then-pay",
            program({"do": "Look.", "use": {"kind": "skill", "id": "sk_look_or_escalate"}, "ifNot": once}, paid),
        ),
        stepped("sk_look_then_note", 1, "Look then note pay", "look-then-note-pay", program(looked, noted, paid)),
        stepped(
            "sk_note_or_skip",
            1,
            "Note or skip",
            "note-or-skip",
            program({**noted, "ifNot": {"action": "retry", "retries": 1}}, exit={"skip": "Go on without the note."}),
        ),
        stepped(
            "sk_jump_runs_note",
            1,
            "Jump runs note",
            "jump-runs-note",
            program(
                {**looked, "ifNot": {"action": "goto", "step": 2}},
                {"do": "Note it.", "use": {"kind": "skill", "id": "sk_note_or_skip"}},
                paid,
            ),
        ),
        stepped("sk_letter_check_pay", 1, "Letter check pay", "letter-check-pay", program(letter, looked, paid)),
        stepped(
            "sk_runs_look_retry",
            1,
            "Runs look retry",
            "runs-look-retry",
            program({"do": "Look.", "use": {"kind": "skill", "id": "sk_look_or_escalate"}}, paid),
        ),
        stepped(
            "sk_look_ok",
            1,
            "Look ok",
            "look-ok",
            program(
                {**looked, "ifNot": {"action": "retry", "retries": 1}},
                exit={"skip": "Go on without it."},
                returns=[{"name": "ok", "type": "yes_no"}],
            ),
        ),
        *[
            stepped(
                f"sk_rule_{key}",
                1,
                f"Rule {key}",
                f"rule-{key}",
                program(
                    {
                        "do": "Look.",
                        "use": {"kind": "skill", "id": "sk_look_ok"},
                        "check": {"text": text, "by": "rule"},
                        "ifNot": once,
                    },
                    paid,
                ),
            )
            for key, text in PARENT_RULES.items()
        ],
        stepped(
            "sk_skip_is_fine",
            1,
            "Skip is fine",
            "skip-is-fine",
            program(
                {
                    "do": "Note it.",
                    "use": {"kind": "skill", "id": "sk_note_or_skip"},
                    "check": {"text": 'result.exit in ["done", "skip"]', "by": "rule"},
                },
                paid,
            ),
        ),
        stepped(
            "sk_check_jump",
            1,
            "Check jump",
            "check-jump",
            program(
                {**looked, "ifNot": {"action": "goto", "step": 3}},
                paid,
                {
                    "do": "Check who asks.",
                    "use": {"kind": "tool", "id": "check_id"},
                    "check": {"text": "result.ok is true", "by": "rule"},
                    "ifNot": once,
                },
                letter,
            ),
        ),
    ]


def _saved(arguments: dict[str, Any]) -> dict[str, Any]:
    return {"saved": arguments["chargeId"] == "CH-2"}


def _known(arguments: dict[str, Any]) -> dict[str, Any]:
    return {"ok": arguments["chargeId"] == "CH-2"}


class Bank(Systems):
    """The systems of the threads below; a tool named in `down` answers with an error."""

    def __init__(self, down: frozenset[str]) -> None:
        super().__init__(
            lookup_charge=_amount,
            refund_charge={"refunded": True},
            add_note=_saved,
            check_id=_known,
            place_hold={"held": True},
        )
        self.down = down

    async def execute(self, tool: str, arguments: dict[str, Any], *, key: str, approval_token: str | None) -> Any:
        if tool in self.down:
            self.calls.append((tool, arguments))
            return ToolOutcome(False, {"error": "The system is down."})
        return await super().execute(tool, arguments, key=key, approval_token=approval_token)


Change = Callable[[list[Skill]], list[Skill]]


@dataclass(frozen=True)
class Thread:
    """One conversation: what the model does in each reply, the calls that reach a system over all of them, and a
    sentence the model must have been told. A reply may first change the agent's skills. A call that pauses for a
    person is denied."""

    name: str
    replies: list[list[Action] | tuple[Change, list[Action]]]
    calls: list[str]
    told: str = ""
    if_not: dict[str, Any] = field(default_factory=lambda: {"action": "retry", "retries": 0})
    redact: bool = False
    down: frozenset[str] = frozenset()


HELD = "refund_charge is held because check-then-pay failed its check; start check-then-pay again."
ONE_MORE = {"action": "retry", "retries": 1}

THREADS = [
    # Rule 1: the hold is taken when the check fails, whatever retries are left and however the skill is left.
    Thread(
        "a retry is left and the model gives up",
        [[CHECK, look("CH-1"), GIVE_UP], [PAY, refund("CH-1")]],
        ["lookup_charge"],
        HELD,
        ONE_MORE,
    ),
    Thread(
        "a retry is left and the reply ends",
        [[CHECK, look("CH-1")], [PAY, refund("CH-1")]],
        ["lookup_charge"],
        HELD,
        ONE_MORE,
    ),
    Thread(
        "a retry is left and the model switches in the same reply",
        [[CHECK, look("CH-1"), PAY, refund("CH-1")]],
        ["lookup_charge"],
        HELD,
        ONE_MORE,
    ),
    # Rules 2 and 3: later steps' tools are held from every other skill and from a plain call; the failed step's
    # own tool is not.
    Thread(
        "no skill running",
        [[CHECK, look("CH-1"), refund("CH-1")], [refund("CH-1"), look("CH-1")]],
        ["lookup_charge", "lookup_charge"],
    ),
    Thread(
        "a skill that gave up first is not the holder",
        [[PAY, GIVE_UP], [CHECK, look("CH-1")], [PAY, refund("CH-1")]],
        ["lookup_charge"],
        HELD,
    ),
    Thread(
        "another skill gave up on a free step first",
        [[GOODWILL, GIVE_UP], [CHECK, look("CH-1")], [GOODWILL, DONE, refund("CH-1")]],
        ["lookup_charge"],
        HELD,
    ),
    Thread(
        "another skill gives up after, then starts again",
        [[CHECK, look("CH-1")], [GOODWILL, GIVE_UP], [GOODWILL, DONE, refund("CH-1")]],
        ["lookup_charge"],
        HELD,
    ),
    Thread(
        "more skills ended than the record lists, the record masked",
        [[CHECK, look("CH-1")], *([[PAY, GIVE_UP, refund("CH-1")]] * 6)],
        ["lookup_charge"],
        HELD,
        redact=True,
    ),
    # Rule 4: only the holder passing that step's check releases it.
    Thread(
        "the holder passes its check, and the tool is free again",
        [[CHECK, look("CH-1")], [CHECK, look("CH-2"), refund("CH-2")], [PAY, refund("CH-2")]],
        ["lookup_charge", "lookup_charge", "refund_charge", "refund_charge"],
    ),
    Thread(
        "two skills that name the same tools in opposite order do not lock each other",
        [
            [NOTE_PAY, note("CH-1")],
            [NOTE_PAY, note("CH-2"), LOOK_PAY_NOTE, look("CH-1")],
            [NOTE_PAY, note("CH-2")],
            [LOOK_PAY_NOTE, look("CH-2"), refund("CH-2"), note("CH-2")],
        ],
        ["add_note", "add_note", "lookup_charge", "lookup_charge", "refund_charge", "add_note"],
        "add_note is held because look-pay-note failed its check; start look-pay-note again.",
    ),
    # Rules 4 and 6: the holder leaves the agent, or the agent pins another version of it.
    Thread(
        "the holder is no longer on the agent",
        [[CHECK, look("CH-1")], (lambda skills: skills[1:], [PAY, refund("CH-1")])],
        ["lookup_charge", "refund_charge"],
    ),
    Thread(
        "the agent has another version of the holder",
        [[CHECK, look("CH-1")], (lambda skills: [replace(skills[0], version=2), *skills[1:]], [PAY, refund("CH-1")])],
        ["lookup_charge", "refund_charge"],
    ),
    # Rule 7: a denied call holds the denied tool and the later steps' tools.
    Thread(
        "a person denies a call",
        [[GATED, PLACE], [PAY, refund("CH-1")], [PLACE]],
        [],
        "refund_charge is held because a person denied a call of hold-then-pay; start hold-then-pay again.",
    ),
    Thread(
        "a denied tool is itself held",
        [[GATED, PLACE], [HOLD_ONLY, PLACE]],
        [],
        "place_hold is held because a person denied a call of hold-then-pay; start hold-then-pay again.",
    ),
    # Rule 1, at each place a check runs: inside a skill a step runs, on that skill's result, and on a step with
    # no tool.
    Thread(
        "the check fails inside a skill a step runs, and passing it there releases",
        [
            [RUNS_LOOK, look("CH-1")],
            [PAY, refund("CH-1")],
            [RUNS_LOOK, look("CH-2"), refund("CH-2"), note("CH-2")],
            [PAY, refund("CH-2")],
        ],
        ["lookup_charge", "lookup_charge", "refund_charge", "add_note", "refund_charge"],
        "refund_charge is held because runs-look failed its check; start runs-look again.",
    ),
    Thread(
        "a skill a step ran ends as done and the step's rule on its result fails",
        [[RUNS_SORRY, DONE], [note("CH-2")]],
        [],
    ),
    # An exit the model calls fails the step and takes no hold (rule 8): the model can call it before the skill
    # reaches a tool another skill holds, so a hold here could lock the two. Q fails and holds the note; the parent's
    # skill leaves at once; Q then passes.
    Thread(
        "an exit called at once takes no hold, so two skills do not lock",
        [[LOOK_THEN_LETTER, look("CH-1")], [RUNS_WAIT, SKIP], [LOOK_THEN_LETTER, look("CH-2"), note("CH-2")]],
        ["lookup_charge", "lookup_charge", "add_note"],
    ),
    Thread(
        "a rule on a step with no tool fails",
        [[CONFIRM_NO, DONE], [PAY, refund("CH-1")]],
        [],
        "refund_charge is held because confirm-then-pay failed its check; start confirm-then-pay again.",
    ),
    Thread(
        "a skill a step runs fails its check with a retry left, then leaves through an exit it lists",
        [[RUNS_LOOK_PAY, look("CH-1"), ("exit", {"name": "escalate"}), refund("CH-1")], [refund("CH-1")]],
        ["lookup_charge"],
    ),
    Thread(
        "two failures in two runs: passing the earlier step leaves the later hold",
        [
            [LOOK_THEN_NOTE, look("CH-2"), note("CH-1")],
            [LOOK_THEN_NOTE, look("CH-1")],
            [LOOK_THEN_NOTE, look("CH-2")],
            [PAY, refund("CH-2")],
        ],
        ["lookup_charge", "add_note", "lookup_charge", "lookup_charge"],
        "refund_charge is held because look-then-note-pay failed its check; start look-then-note-pay again.",
    ),
    # A step that runs a skill passes only on done, unless it has a rule of its own: however often the model calls
    # a listed exit, it does not carry the step past the check that failed inside.
    Thread(
        "a listed exit called twice in one reply",
        [[RUNS_LOOK_RETRY, look("CH-1"), ESCALATE, ESCALATE, refund("CH-1")]],
        ["lookup_charge"],
    ),
    Thread(
        "a listed exit called again after the parent is started again",
        [[RUNS_LOOK_PAY, look("CH-1"), ESCALATE], [RUNS_LOOK_PAY, ESCALATE, refund("CH-1")]],
        ["lookup_charge"],
    ),
    Thread(
        "a skill reached by a jump past a failed check fails its own, then a listed exit is called twice",
        [[JUMP_RUNS_NOTE, look("CH-1"), note("CH-1"), SKIP, SKIP, refund("CH-1")]],
        ["lookup_charge", "add_note"],
    ),
    # The step's rule reads the results a skill hands back only when it ended as done: with any other exit the
    # model names the results itself, so it could say ok and carry the step past the check that failed inside.
    # After any exit but done, the step's rule must depend on the exit: it has to hold for this exit and not hold
    # for one the skill does not list. A rule about a result, or about something else altogether, does not pass.
    *[
        Thread(
            f"after a failed check inside and a listed exit, the step's rule is {PARENT_RULES[key]}",
            [[after_skip(key), look("CH-1"), SKIP_OK, refund("CH-1")]],
            ["lookup_charge", "refund_charge"] if goes_on else ["lookup_charge"],
        )
        for key, goes_on in {
            "ok_true": False,
            "ok_ne_false": False,
            "ok_not_false": False,
            "tier": False,
            "names_skip": True,
            "not_failed": True,
        }.items()
    ],
    Thread(
        "a step with a rule of its own that accepts a listed exit goes on",
        [[SKIP_IS_FINE, SKIP, refund("CH-2")]],
        ["refund_charge"],
    ),
    # X is letter, check, refund; H is check with a jump to 3, refund, check, letter. X fails its check and holds the
    # refund; H fails both of its checks. Were H to take a second hold, X would end on the letter and H on the
    # refund for good. With one hold, H passes its first step and X runs.
    Thread(
        "a forward jump does not lock two skills",
        [
            [LETTER_CHECK_PAY, note("CH-2"), look("CH-1")],
            [CHECK_JUMP, look("CH-1"), ("check_id", {"chargeId": "CH-1"})],
            [LETTER_CHECK_PAY],
            [CHECK_JUMP, look("CH-2")],
            [LETTER_CHECK_PAY, note("CH-2"), look("CH-2"), refund("CH-2")],
        ],
        [
            "add_note",
            "lookup_charge",
            "lookup_charge",
            "check_id",
            "lookup_charge",
            "add_note",
            "lookup_charge",
            "refund_charge",
        ],
        "refund_charge is held because letter-check-pay failed its check; start letter-check-pay again.",
    ),
    # Rule 5: a step takes no hold while its skill has one standing from an earlier step. Once the earlier step
    # passes, nothing is left of the later step's failure: an accepted limit, the price of never locking.
    Thread(
        "a later step fails while an earlier hold stands",
        [[LOOK_NOTE_PAY, look("CH-1"), note("CH-1")], [LOOK_NOTE_PAY, look("CH-2")], [PAY, refund("CH-2")]],
        ["lookup_charge", "add_note", "lookup_charge", "refund_charge"],
    ),
    # Rule 8: a failure that is not a check takes no hold.
    Thread(
        "the step's tool answers with an error",
        [[CHECK, look("CH-1")], [PAY, refund("CH-1")]],
        ["lookup_charge", "refund_charge"],
        down=frozenset({"lookup_charge"}),
    ),
    Thread("a step cannot start its skill", [[RUNS_NEEDY], [PAY, refund("CH-2")]], ["refund_charge"]),
    # Accepted: the holder's own if-not jump to a later write is the author's path; a thread with no failure holds
    # nothing.
    Thread(
        "the holder's own jump to its write",
        [[CHECK, look("CH-1"), refund("CH-1")]],
        ["lookup_charge", "refund_charge"],
        if_not={"action": "goto", "step": 2},
    ),
    Thread("nothing failed", [[PAY, refund("CH-1")]], ["refund_charge"]),
]


@pytest.mark.parametrize("thread", THREADS, ids=lambda t: t.name)
async def test_a_failed_check_or_a_denied_call_holds_the_later_tools_until_the_holder_passes(thread: Thread) -> None:
    skills = book(thread.if_not)
    systems = Bank(thread.down)
    run: Any = None
    told: list[Any] = []
    for n, step in enumerate(thread.replies, start=1):
        change, actions = step if isinstance(step, tuple) else (None, step)
        skills = change(skills) if change is not None else skills
        settings = agent(skills, redact_pii=thread.redact, max_steps=12)
        ask = TurnRequest(
            f"t{n}", "th1", settings, [LOOKUP, REFUND, NOTE, GATE, ID_CHECK], user_turn="Go on.", carried_run=run
        )
        model = Script(*actions, "Done.")
        result, _ = await reply(ask, model, systems)
        if result.status == "interrupted":
            assert result.interrupt is not None
            denied = Resume(result.interrupt, "rejected", reason="No.")
            model = Script("It was denied.")
            result, _ = await reply(replace(ask, turn_id=f"t{n}d", user_turn=None, resume=denied), model, systems)
        told += model.returned
        run = run_of(result)
    assert [c for c, _ in systems.calls] == thread.calls, systems.calls
    assert thread.told in json.dumps(told), told


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
    skills = pay_out_after_a_check({"action": "retry"}, exit={"escalate": "Hand the request to a person."})
    ask = TurnRequest("t1", "th1", agent(skills, max_steps=12), [LOOKUP, REFUND, NOTE], user_turn="Refund CH-1.")
    systems = Systems(lookup_charge=_amount, refund_charge={"refunded": True})
    model = Script(
        ("switch_skill", {"slug": "check-then-pay"}),
        # No check failed: the model hands the request to a person, which holds for this reply only.
        ("exit", {"name": "escalate"}),
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
    assert systems.calls == [], systems.calls

    # The next reply is free of it: no check failed and no call was denied.
    later = Script(("switch_skill", {"slug": "pay-out"}), ("refund_charge", {"chargeId": "CH-1"}), "CH-1 is refunded.")
    await reply(replace(carrying(ask, run_of(result)), turn_id="t2", user_turn="Pay it out."), later, systems)
    assert [c for c, _ in systems.calls] == ["refund_charge"], systems.calls


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
    """A scripted model that records the reasoning effort each request sent to the gateway."""

    def __init__(self, *actions: Any) -> None:
        super().__init__(*actions)
        self.thinking: list[Any] = []

    def respond(self, messages: list[Json], tools: list[Json], body: Json | None = None) -> Answer:
        self.thinking.append((body or {}).get("reasoning_effort"))
        return super().respond(messages, tools, body)


async def test_a_saved_agent_sends_no_thinking_setting_and_a_set_one_reaches_the_model() -> None:
    settings = load_catalog(SEED).settings_for(definition_of("ag_branch", 3, LEGACY_SPEC), "m")
    ask = TurnRequest("t1", "th1", settings, [], user_turn="When does the branch open?")
    legacy = ThinkingScript("The branch opens at nine.")
    await reply(ask, legacy)
    assert legacy.thinking == [None], "a saved agent with no thinking setting sends none"

    low = ThinkingScript("The branch opens at nine.")
    await reply(replace(ask, settings=replace(settings, thinking="low")), low)
    assert low.thinking == ["low"], "the scripted model sees a thinking setting when one is sent"


async def test_an_input_handed_to_a_sub_skill_is_masked_in_the_record_a_reply_returns() -> None:
    """A step that runs a skill hands it the running skill's inputs. With masking on, the copy the sub-skill holds
    leaves the reply masked like the parent's own, and marked so no rule compares the placeholder."""
    verify = replace(
        stepped("sk_verify", 1, "Verify identity", "verify-identity", program({"do": "Ask for the date of birth."})),
        inputs=(SkillInput("ssn", required=True),),
    )
    parent = program({"do": "Verify the person.", "use": {"kind": "skill", "id": "sk_verify"}}, {"do": "Go on."})
    close = replace(
        stepped("sk_close", 1, "Close an account", "close-an-account", parent),
        inputs=(SkillInput("ssn", required=True),),
    )
    ask = TurnRequest("t1", "th1", agent([close, verify], redact_pii=True), [], user_turn="Close my account.")
    model = Script(
        ("switch_skill", {"slug": "close-an-account", "inputs": {"ssn": SSN}}), "What is your date of birth?"
    )
    result, events = await reply(ask, model)
    sub = run_of(result).running.sub
    assert sub is not None and "ssn" in sub.inputs, run_of(result)
    assert SSN not in sub.inputs["ssn"] and sub.masked_inputs == ["ssn"], sub
    assert SSN not in run_of(result).model_dump_json()
    changes = [e for e in events if type(e).__name__ == "SkillRunChanged"]
    assert changes and all(SSN not in repr(e) for e in changes), changes


class Down(Systems):
    """The refund's system is down: the call comes back failed."""

    async def execute(
        self, tool: str, arguments: dict[str, Any], *, key: str, approval_token: str | None
    ) -> ToolOutcome:
        if tool != "refund_charge":
            return await super().execute(tool, arguments, key=key, approval_token=approval_token)
        self.calls.append((tool, arguments))
        return ToolOutcome(False, {"error": "The payments system did not answer."})


AGAIN = "cannot start again in this reply"


@pytest.mark.parametrize(
    "how", ["a reviewer rejected the write", "the step's tool failed", "another skill holds its tool"]
)
async def test_an_ending_the_kernel_made_keeps_the_skill_from_starting_again_in_that_reply(how: str) -> None:
    """A skill stopped by a rejection, a failed call or a held tool stays stopped for the reply. Started again in the
    same reply it would run its earlier steps a second time and ask for the refused action once more."""
    check, pay = pay_out_after_a_check({"action": "retry"}, exit={"escalate": "Hand the request to a person."})
    write: Call = ("refund_charge", {"chargeId": "CH-2"})
    if how == "another skill holds its tool":
        # check-then-pay is left by its own exit, which holds the refund; pay-out then ends on its first step.
        skills, tools, systems = [check, pay], [LOOKUP, REFUND], Systems(lookup_charge=_amount)
        before: list[Action] = [("switch_skill", {"slug": "check-then-pay"}), ("exit", {"name": "escalate"}), PAY]
    elif how == "the step's tool failed":
        # No second try, so the failed call ends the skill rather than offering the step again.
        once = {
            "do": "Refund the charge.",
            "use": {"kind": "tool", "id": "refund_charge"},
            "ifNot": {"action": "retry", "retries": 0},
        }
        skills, tools, systems = [replace(pay, program=program(once))], [LOOKUP, REFUND], Down(lookup_charge=_amount)
        before = [PAY, write]
    else:
        skills, tools, systems = [pay], [LOOKUP, tool("refund_charge", "write", approval=True)], Systems()
        before = [PAY, write]
    ask = TurnRequest("t1", "th1", agent(skills, max_steps=12), tools, user_turn="Refund CH-2.")
    model = Script(*before, PAY, "It was not paid out.")
    result, _ = await reply(ask, model, systems)
    if result.status == "interrupted":
        assert result.interrupt is not None
        model = Script(PAY, "It was not paid out.")
        rejected = Resume(result.interrupt, "rejected", reason="Not this charge.")
        result, _ = await reply(replace(ask, turn_id="t1d", user_turn=None, resume=rejected), model, systems)
    run = run_of(result)
    assert [e for e in ended(run) if e[0] == "sk_pay"] == [("sk_pay", "failed", 1)], run
    assert run.running is None and AGAIN in json.dumps(model.returned[-1]), model.returned
