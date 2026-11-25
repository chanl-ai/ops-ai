"""The prompt an agent with a brief gets, by failure mode: its sections moving, or the never rules not coming last,
with a skill step running and when the builder wrote the whole prompt.

The order is read from the instructions the model receives, because the platform rules, the skill lists and the
running step are placed by the turn and not by the writer. What this asks beyond the names the design fixes: the
agent's stable fragment is `prompt_writer.head(name, brief)`, and the never rules reach the turn as
`AgentSettings.never`.

The sections a builder adds (`brief.sections`) are read the same way, through what a save stores and what View prompt
shows. What these tests ask beyond the design: a save's refusal of a section is raised by `agent_brief.patched` as an
`ApiError` with status 422 and code `validation_failed` whose message names `brief.sections` (a request model's own
refusal answers 400), and a reply's sections are `BriefView` read from the stored brief.

A workspace that renames Never: the name is read from what a save stores (View prompt) and from the turn. What this
asks beyond the design: the heading reaches the turn as `AgentSettings.never_heading`, beside `AgentSettings.never`."""

from __future__ import annotations

import importlib
from dataclasses import replace
from typing import Any

import pytest
from pydantic import JsonValue

from ops_agent_kernel.context import PLATFORM_RULES
from ops_agent_kernel.prompt_writer import Brief, Now, head, tail
from ops_agent_kernel.types import AgentSettings, PromptFragment, Skill, TurnRequest
from ops_agents.api.schemas import BriefView
from ops_agents.app import agent_brief
from ops_agents.app.instruction_sections import default_list
from ops_service_kit.errors import ApiError
from ops_service_kit.http import Json
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
        hand_off=["The person asks for a human."],
        examples="Q: Is it a fraud charge?\nA: Tell me the amount and the date.",
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
        "# Hand off when",
        "- The person asks for a human.",
        "# Examples",
        "A: Tell me the amount and the date.",
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


def test_a_saved_brief_keeps_hand_off_and_examples_and_an_older_version_reads_as_stored() -> None:
    brief = Brief(
        purpose="Help customers dispute a card charge.",
        how_to_answer="Plain words.",
        hand_off=["The person asks for a human."],
        examples="Q: Which charge?\nA: The 200 on the 3rd.",
        never=NEVER,
    )
    saved = agent_brief.patched({"name": "Dispute Desk"}, brief=brief, mode=None, patterns=None, writes_prompt=False)
    assert agent_brief.brief_of(saved) == brief
    shown = agent_brief.prompt_view(saved)
    marks = ["# How to answer", "# Hand off when", "- The person asks for a human.", "# Examples", "# Never"]
    assert in_order(shown, marks) == marks, shown
    assert shown.rstrip().endswith(NEVER[1]), shown

    # Stored before the two fields: the brief reads with them empty and the prompt is the instructions it was saved
    # with, the never rules after them.
    rules: list[JsonValue] = list(NEVER)
    old_brief: Json = {"purpose": "Answer fee questions.", "howToAnswer": "Short.", "never": rules, "success": []}
    old: Json = {"name": "Fees", "promptMode": "brief", "brief": old_brief, "instructions": "You are Fees. Short."}
    read = agent_brief.brief_of(old)
    assert read is not None and read.hand_off == [] and read.examples == ""
    assert agent_brief.prompt_view(old) == "You are Fees. Short.\n\n# Never\n- " + "\n- ".join(NEVER)


PURPOSE = "Help customers dispute a card charge."


def saved_with(sections: list[dict[str, str]], **fields: object) -> Json:
    """The agent a save of a brief with these sections stores."""
    brief = Brief.model_validate({"purpose": PURPOSE, "never": NEVER, **fields, "sections": sections})
    return agent_brief.patched({"name": "Dispute Desk"}, brief=brief, mode=None, patterns=None, writes_prompt=False)


def refusal(sections: list[dict[str, str]]) -> str:
    """What a save of these sections is refused with; the message, once the status and the code are the design's."""
    with pytest.raises(ApiError) as said:
        saved_with(sections)
    assert (said.value.status, said.value.code) == (422, "validation_failed"), said.value
    return said.value.message


def custom(name: str, text: str = "Say it plainly.") -> dict[str, str]:
    return {"kind": "custom", "name": name, "text": text}


def test_added_sections_take_their_fixed_places_whatever_order_they_were_saved_in_and_never_stays_last() -> None:
    saved = saved_with(
        [
            {"kind": "escalation", "text": "Say: I am passing you to a colleague."},
            custom("Refund wording", "Say refund, never reimbursement."),
            {"kind": "error_handling", "text": "If a tool fails, say so and try once more."},
            {"kind": "tone", "text": " Calm and plain. "},
            {"kind": "context", "text": "Disputes close after 120 days."},
            custom("Left blank", "  "),
            {"kind": "environment", "text": "You answer in the bank's chat."},
            {"kind": "tool_use", "text": "Read the charge before you answer."},
            {"kind": "personality", "text": "Patient."},
        ],
        goal="Every dispute is opened with the right charge.",
        howToAnswer="Two short paragraphs at most.",
        handOff=["The person asks for a human."],
        examples="Q: Is it fraud?\nA: Tell me the amount.",
    )
    assert agent_brief.prompt_view(saved) == (
        "# Who you are\nYou are Dispute Desk.\nYour job: Help customers dispute a card charge.\n\n"
        "# Goal\nEvery dispute is opened with the right charge.\n\n"
        "# Personality\nPatient.\n\n"
        "# Tone\nCalm and plain.\n\n"
        "# Environment\nYou answer in the bank's chat.\n\n"
        "# Context\nDisputes close after 120 days.\n\n"
        "# How to answer\nTwo short paragraphs at most.\n\n"
        "# Tool use\nRead the charge before you answer.\n\n"
        "# Error handling\nIf a tool fails, say so and try once more.\n\n"
        "# Refund wording\nSay refund, never reimbursement.\n\n"
        "# Hand off when\n- The person asks for a human.\n\n"
        "# Escalation wording\nSay: I am passing you to a colleague.\n\n"
        "# Examples\nQ: Is it fraud?\nA: Tell me the amount.\n\n"
        "# Never\n- Never promise a refund date.\n- Never name another customer."
    )


def test_custom_sections_keep_the_order_they_were_saved_in() -> None:
    saved = saved_with(
        [custom("Zone hours"), {"kind": "tone", "text": "Calm."}, custom("Account words"), custom("Mail wording")],
        howToAnswer="Short.",
        handOff=["The person asks for a human."],
    )
    marks = ["# Tone", "# How to answer", "# Zone hours", "# Account words", "# Mail wording", "# Hand off when"]
    shown = agent_brief.prompt_view(saved)
    assert in_order(shown, marks) == marks, shown


def test_a_custom_section_named_like_a_fixed_heading_or_like_another_custom_section_is_refused() -> None:
    kept = agent_brief.prompt_view(saved_with([custom("Refund wording")]))
    assert "# Refund wording\nSay it plainly." in kept, kept
    taken = {
        "another case": [custom("never")],
        "spaces around and inside": [custom("  Hand   off  when ")],
        "a section from the menu": [custom("Tool use")],
        "a field no longer asked for": [custom("Success checks")],
        "the same custom name twice": [custom("Refund wording"), custom("Refund wording")],
    }
    for why, sections in taken.items():
        assert "brief.sections" in refusal(sections), why


def test_a_sixth_custom_section_and_a_menu_section_added_twice_are_refused() -> None:
    five = [custom(f"Topic {n}", f"Text {n}.") for n in range(1, 6)]
    tone = {"kind": "tone", "text": "Calm."}
    shown = agent_brief.prompt_view(saved_with([*five, tone]))
    marks = ["# Tone", *(f"# Topic {n}" for n in range(1, 6)), "# Never"]
    assert in_order(shown, marks) == marks, shown
    assert "brief.sections" in refusal([*five, custom("Topic 6")])
    assert "brief.sections" in refusal([tone, {"kind": "tone", "text": "Warm."}])


def test_a_brief_stored_without_sections_writes_the_prompt_it_wrote_before_them() -> None:
    stored: Json = {
        "purpose": " Help customers dispute a card charge. ",
        "goal": "Every dispute is opened with the right charge.",
        "howToAnswer": "Plain words, two short paragraphs at most.",
        "handOff": ["The person asks for a human.", " The charge is older than 120 days. "],
        "examples": "Q: Is it a fraud charge?\nA: Tell me the amount and the date.",
        "never": list[JsonValue](NEVER),
        "success": ["The dispute is opened."],
    }
    brief = Brief.model_validate(stored)
    now = Now("Open a dispute", 1, 2, "Ask which charge.", rules="Quote the charge amount back to the person.")
    assert head("Dispute Desk", brief) == (
        "# Who you are\nYou are Dispute Desk.\nYour job: Help customers dispute a card charge.\n\n"
        "# Goal\nEvery dispute is opened with the right charge.\n\n"
        "# How to answer\nPlain words, two short paragraphs at most.\n\n"
        "# Hand off when\n- The person asks for a human.\n- The charge is older than 120 days.\n\n"
        "# Examples\nQ: Is it a fraud charge?\nA: Tell me the amount and the date."
    )
    assert tail(now, brief.never) == (
        "# Now: Open a dispute, step 1 of 2\nAsk which charge.\n"
        "Done when: you have done it; then call step_done.\n"
        "Do only this step. If the person now asks for something else, call switch_skill or exit.\n\n"
        "# Rules for this skill\nQuote the charge amount back to the person.\n\n"
        "# Never\n- Never promise a refund date.\n- Never name another customer."
    )


def test_a_saved_section_is_replied_with_its_kind_and_title_and_an_older_brief_replies_none() -> None:
    saved = saved_with(
        [{"kind": "tone", "text": "Calm."}, custom("Refund wording", "Say refund."), custom("Later", "")]
    )
    replied = BriefView.model_validate(saved["brief"]).model_dump(by_alias=True)
    assert replied["sections"] == [
        {"kind": "tone", "name": "Tone", "text": "Calm."},
        {"kind": "custom", "name": "Refund wording", "text": "Say refund."},
        {"kind": "custom", "name": "Later", "text": ""},
    ]
    # The section saved empty is kept for the builder and is not sent to the model.
    assert "# Later" not in agent_brief.prompt_view(saved)

    old: Json = {"purpose": "Answer fee questions.", "howToAnswer": "Short.", "never": [], "success": []}
    assert BriefView.model_validate(old).model_dump(by_alias=True)["sections"] == []


async def test_a_list_that_renames_never_writes_the_never_rules_under_its_name_and_still_last() -> None:
    listing = default_list()
    renamed = listing.model_copy(
        update={
            "sections": [
                x.model_copy(update={"label": "Hard limits"}) if x.id == "never" else x for x in listing.sections
            ]
        }
    )
    brief = Brief.model_validate({"purpose": PURPOSE, "howToAnswer": "Two short paragraphs at most.", "never": NEVER})
    saved = agent_brief.patched(
        {"name": "Dispute Desk"}, brief=brief, mode=None, patterns=None, writes_prompt=False, listing=renamed
    )
    assert agent_brief.prompt_view(saved) == (
        "# Who you are\nYou are Dispute Desk.\nYour job: Help customers dispute a card charge.\n\n"
        "# How to answer\nTwo short paragraphs at most.\n\n"
        "# Hard limits\n- Never promise a refund date.\n- Never name another customer."
    )

    # With a skill step running, the renamed heading still follows the step and the skill's rules.
    dispute = stepped(
        "sk_open",
        1,
        "Open a dispute",
        "open-a-dispute",
        program({"do": "Ask which charge."}, {"do": "Open the dispute."}),
        rules="Quote the charge amount back to the person.",
    )
    fragments = [PromptFragment(str(saved["instructions"]))]
    settings: Any = replace(AgentSettings("ag_disputes", 1, fragments, "m", skills=[dispute]), never=NEVER)
    settings = replace(settings, never_heading="Hard limits")
    model = Script(("switch_skill", {"slug": "open-a-dispute"}), "Which charge is it?")
    await reply(TurnRequest("t1", "th1", settings, [], user_turn="I want to dispute a charge."), model)
    sent = model.instructions[1]
    marks = ["# Now: Open a dispute, step 1 of 2", "# Rules for this skill", "# Hard limits", NEVER[0], NEVER[1]]
    assert in_order(sent, marks) == marks, sent
    assert "# Never" not in sent and sent.rstrip().endswith(NEVER[1]), sent[-300:]
