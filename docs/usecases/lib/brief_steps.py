"""Shared data for uc-757 (an agent written as a brief, with a skill that runs step by step): the skill, the skill
one of its steps runs, and the brief, as a builder writes them through the API, the SDK or the CLI."""

from __future__ import annotations

from typing import Any


def confirm_skill(run: int, layer: str) -> dict[str, Any]:
    """A one-step skill another skill runs as a step; its check is a sentence, so the agent confirms it."""
    return {
        "name": f"Confirm the caller {layer} {run}",
        "ownerTeam": "team_ops",
        "useWhen": "The caller must be confirmed before an account is changed.",
        # The create call asks for the field; a skill with steps may leave its shared notes empty.
        "instructions": "",
        "steps": [
            {
                "do": "Ask the caller for their date of birth and compare it with the record.",
                "check": {"text": "The date of birth matches the record."},
            }
        ],
    }


def freeze_skill(run: int, layer: str, read: str, write: str, confirm_id: str) -> dict[str, Any]:
    """Three steps: a read with a rule check, a skill, then a write that waits for a person's approval."""
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
            {"do": "Freeze the account.", "use": {"kind": "tool", "id": write}},
        ],
        "exit": {"refused": "The caller could not be confirmed."},
        "success": ["The caller was confirmed before the freeze."],
    }


def brief(read: str) -> dict[str, Any]:
    return {
        "purpose": "Reads and freezes accounts for callers.",
        "goal": "The caller's account is frozen, or they know why it was not.",
        "howToAnswer": f"Read the account with @tool:{read} before you say anything about it. Keep answers short.",
        "never": ["Never promise when a freeze will be lifted."],
        "success": ["The caller knows whether the account is frozen."],
    }
