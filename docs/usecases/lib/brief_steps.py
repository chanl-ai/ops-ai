"""Shared data for uc-757 (an agent written as a brief, with a skill that runs step by step): the skill, the skill
one of its steps runs, and the brief, as a builder writes them through the API, the SDK or the CLI."""

from __future__ import annotations

from typing import Any

# What the bank answers a hold with. A step that changes something carries a rule on its result, and an ending for
# when the rule does not hold: left to the default, the step would offer the write again.
PLACED: dict[str, Any] = {"check": {"text": 'result.hold == "placed"'}, "ifNot": {"action": "exit", "exit": "failed"}}


# The date of birth on the fake bank's record, which a caller gives to pass the confirm step.
DATE_OF_BIRTH = "1984-03-02"
# What a person says to pass that step: the date, then the scripted model's call of step_done.
CONFIRMS = f"My date of birth is {DATE_OF_BIRTH}. call step_done {{}}"


def confirm_skill(run: int, layer: str) -> dict[str, Any]:
    """A one-step skill another skill runs as a step; its check is a sentence, so the judge decides it from what the
    person wrote in that reply. The scripted judge passes a check whose quoted words the evidence holds."""
    return {
        "name": f"Confirm the caller {layer} {run}",
        "ownerTeam": "team_ops",
        "useWhen": "The caller must be confirmed before an account is changed.",
        # The create call asks for the field; a skill with steps may leave its shared notes empty.
        "instructions": "",
        "steps": [
            {
                "do": "Ask the caller for their date of birth and compare it with the record.",
                "check": {"text": f'The caller gave the date of birth on the record, "{DATE_OF_BIRTH}".'},
            }
        ],
    }


def freeze_skill(run: int, layer: str, read: str, write: str, confirm_id: str) -> dict[str, Any]:
    """Three steps: a read with a rule check, a skill, then a write that waits for a person's approval and is checked
    by a rule on what the bank answered."""
    return {
        "name": f"Freeze an account {layer} {run}",
        "ownerTeam": "team_ops",
        "useWhen": "The caller asks for their account to be frozen.",
        "notWhen": "The caller only asks what a freeze does.",
        "instructions": "Say what each step found before moving on.",
        "steps": [
            {
                "do": f"Read the account with @tool:{read}.",
                "use": {"kind": "tool", "id": read},
                "check": {"text": "result.balance >= 0"},
                "ifNot": {"action": "retry", "retries": 1},
            },
            {"do": "Confirm the caller.", "use": {"kind": "skill", "id": confirm_id}},
            {"do": "Freeze the account.", "use": {"kind": "tool", "id": write}, **PLACED},
        ],
        "exit": {"refused": "The caller could not be confirmed."},
        "success": ["The caller was confirmed before the freeze."],
    }


def hold_skill(run: int, layer: str, read: str, write: str) -> dict[str, Any]:
    """Two steps as the console saves them, each tool picked inside its sentence and stored as the step's tool: a read
    whose rule ends the skill as blocked on an account that owes money, then the write."""
    return {
        "name": f"Hold on a balance {layer} {run}",
        "ownerTeam": "team_ops",
        "useWhen": "The caller asks for a hold to be placed on an account.",
        "instructions": "",
        "steps": [
            {
                "do": f"Look up the account with @tool:{read} and read its balance.",
                "use": {"kind": "tool", "id": read},
                "check": {"text": "result.balance > 0"},
                "ifNot": {"action": "exit", "exit": "blocked"},
            },
            {
                "do": f"Place a hold on the account with @tool:{write} for the reason given.",
                "use": {"kind": "tool", "id": write},
                **PLACED,
            },
        ],
        "exit": {"blocked": "The account has nothing to hold."},
    }


def brief(read: str) -> dict[str, Any]:
    return {
        "purpose": "Reads and freezes accounts for callers.",
        "goal": "The caller's account is frozen, or they know why it was not.",
        "howToAnswer": f"Read the account with @tool:{read} before you say anything about it. Keep answers short.",
        "never": ["Never promise when a freeze will be lifted."],
        "success": ["The caller knows whether the account is frozen."],
    }


# The sections a builder adds to a brief, saved out of their prompt order on purpose: the custom one first, Tone after.
SECTIONS: list[dict[str, str]] = [
    {"kind": "custom", "name": "Freeze wording", "text": "Say freeze, never lock or block."},
    {"kind": "tone", "text": "Calm and plain."},
]
SECTION_HEADINGS = ["# Who you are", "# Tone", "# How to answer", "# Freeze wording", "# Hand off when", "# Never"]


def sections_brief(sections: list[dict[str, str]] | None = None) -> dict[str, Any]:
    """A brief that mentions nothing, with a hand-off rule so a custom section's place before it shows; `sections`
    None leaves the field out, as every brief saved before sections did."""
    body: dict[str, Any] = {
        "purpose": "Freezes accounts for callers.",
        "howToAnswer": "Keep answers short.",
        "handOff": ["The caller asks for a person."],
        "never": ["Never promise when a freeze will be lifted."],
    }
    return body if sections is None else {**body, "sections": sections}


def headings(prompt: str) -> list[str]:
    """The prompt's headings in the order the model reads them."""
    return [line for line in prompt.splitlines() if line.startswith("# ")]


# The workspace's list of sections (steps 29 to 32): an admin adds one of the workspace's own and renames Tone, so an
# agent saved before the change shows whether its prompt was rewritten.
SECTIONS_ROUTE = "/v1/agent-instruction-sections"
COMPLIANCE: dict[str, Any] = {
    "label": "Compliance notes",
    "hint": "What the regulator asks the agent to say.",
    "kind": "menu",
    "required": False,
    "hidden": False,
    "drives": "none",
}
COMPLIANCE_TEXT = "Say the call is recorded."
COMPLIANCE_HEADINGS = ["# Who you are", "# Voice", "# Compliance notes", "# How to answer", "# Hand off when", "# Never"]


def with_compliance(listing: dict[str, Any]) -> dict[str, Any]:
    """The list an admin saves from the one read: Tone renamed Voice and Compliance notes placed straight after it,
    which is before How to answer, so a list that only appends a new section fails the heading order."""
    items = sorted(listing.get("sections") or [], key=lambda s: s.get("order", 0))
    at = next((n + 1 for n, s in enumerate(items) if s.get("id") == "tone"), len(items))
    renamed = [{**s, "label": "Voice"} if s.get("id") == "tone" else s for s in items]
    placed = [*renamed[:at], COMPLIANCE, *renamed[at:]]
    return {**listing, "sections": [{**s, "order": n} for n, s in enumerate(placed)]}


def compliance_id(listing: Any) -> str:
    """The id the service gave Compliance notes, read from a list; empty when the list does not hold it."""
    sections = listing.get("sections") if isinstance(listing, dict) else None
    return next((str(s.get("id", "")) for s in sections or [] if s.get("label") == "Compliance notes"), "")


def compliance_sections(section_id: str) -> list[dict[str, str]]:
    """What a builder adds once the list holds it: the workspace's section and Tone, saved in that order."""
    return [{"kind": section_id, "text": COMPLIANCE_TEXT}, {"kind": "tone", "text": "Calm and plain."}]
