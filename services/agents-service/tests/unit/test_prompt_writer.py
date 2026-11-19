"""The prompt an agent with a brief gets, by failure mode: its sections moving, or the never rules not coming last,
with a skill step running and when the builder wrote the whole prompt.

The order is read from the instructions the model receives, because the platform rules, the skill lists and the
running step are placed by the turn and not by the writer. What this asks beyond the names the design fixes: the
agent's stable fragment is `prompt_writer.head(name, brief)`, and the never rules reach the turn as
`AgentSettings.never`."""

from __future__ import annotations

import importlib
from dataclasses import replace
from typing import Any

from ops_agent_kernel.context import PLATFORM_RULES
from ops_agent_kernel.types import AgentSettings, PromptFragment, Skill, TurnRequest
from tests.unit.test_skill_steps_kernel import Script, program, reply, stepped

NEVER = ["Never promise a refund date.", "Never name another customer."]
ADDED = "Added by the person for this conversation, after your instructions:\nAnswer in French."
READ = 'lookup_charge {"chargeId": "CH-1"} answered {"amount": 200}'
DISCLOSURE = Skill("sk_always", 1, "Bank disclosure", "bank-disclosure", "", "always", "End with: member CDIC.")
FEES = Skill("sk_fees", 1, "Fee waiver", "fee-waiver", "Asks about a fee.", "on_match", "Waive once a year.")


def in_order(text: str, marks: list[str]) -> list[str]:
    """The marks as they come in `text`; one that is missing is listed as missing."""
    found = sorted((text.find(m), m) for m in marks)
    return [m if at >= 0 else f"missing: {m}" for at, m in found]


async def test_the_sections_keep_their_order_and_the_never_rules_come_last_in_both_modes() -> None:
    writer: Any = importlib.import_module("ops_agent_kernel.prompt_writer")
    brief = writer.Brief(
        purpose="Help customers dispute a card charge.",
        goal="Every dispute is opened with the right charge.",
        how_to_answer="Plain words, two short paragraphs at most.",
        never=NEVER,
    )
    dispute = stepped(
        "sk_open",
        1,
        "Open a dispute",
        "open-a-dispute",
        program({"do": "Ask which charge."}, {"do": "Open the dispute."}),
        rules="Quote the charge amount back to the person.",
    )
    card = stepped("sk_card", 1, "Close a card", "close-a-card", program({"do": "Confirm the card."}))
    fragments = [PromptFragment(writer.head("Dispute Desk", brief)), PromptFragment(ADDED, stable=False)]
    settings = replace(
        AgentSettings("ag_disputes", 1, fragments, "m", skills=[DISCLOSURE, FEES, dispute, card]), never=NEVER
    )
    model = Script(("switch_skill", {"slug": "open-a-dispute"}), "Which charge is it?")
    ask = TurnRequest("t1", "th1", settings, [], user_turn="I want to dispute a charge.", earlier_reads=[READ])
    await reply(ask, model)
    sent = model.instructions[1]
    sections = [
        "# Who you are",
        "You are Dispute Desk.",
        "Help customers dispute a card charge.",
        "# Goal",
        "# How to answer",
        PLATFORM_RULES,
        ADDED,
        DISCLOSURE.instructions,
        "Skills you can load",
        "Skills you can start",
        READ,
        "# Now: Open a dispute, step 1 of 2",
        "# Rules for this skill",
        "Quote the charge amount back to the person.",
        "# Never",
        NEVER[0],
        NEVER[1],
    ]
    assert in_order(sent, sections) == sections, sent
    assert sent.rstrip().endswith(NEVER[1]), sent[-300:]

    # The builder wrote the whole prompt: it is sent as written, and the never rules still follow everything else.
    own = "You are the disputes desk. Answer in two lines."
    full = replace(AgentSettings("ag_disputes", 2, [PromptFragment(own)], "m", skills=[FEES]), never=NEVER)
    model = Script("Which charge is it?")
    await reply(replace(ask, settings=full), model)
    sent = model.instructions[0]
    marks = [own, PLATFORM_RULES, "Skills you can load", "# Never", NEVER[0], NEVER[1]]
    assert in_order(sent, marks) == marks, sent
    assert "# Who you are" not in sent and sent.rstrip().endswith(NEVER[1]), sent
