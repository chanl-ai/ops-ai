"""Publish a skill, give it to an agent, and pick it for one reply."""

from __future__ import annotations

from typing import Any, TypedDict, cast

from ops_ai import OpsAI


class SkillRecord(TypedDict):
    id: str


class AgentRecord(TypedDict):
    id: str


class ThreadRecord(TypedDict):
    id: str


class ChatEvent(TypedDict, total=False):
    type: str
    message: dict[str, Any]


def main() -> None:
    ops = OpsAI()

    skill = cast(
        SkillRecord,
        ops.skills.create(
            {
                "name": "Return checklist",
                "ownerTeam": "Customer Operations",
                "useWhen": "A customer wants to return an item.",
                "loading": "on_match",
                "instructions": (
                    "1. Ask for the order number.\n"
                    "2. Check the purchase date is within 30 days.\n"
                    "3. Ask whether the customer has the receipt.\n"
                    "4. Never promise a refund for a sale item."
                ),
                "inputs": [
                    {
                        "name": "order_number",
                        "description": "The order being returned",
                    }
                ],
            }
        ),
    )
    ops.skills.publish(skill["id"], note="First version")

    agent = cast(
        AgentRecord,
        ops.agents.apply(
            {
                "name": "Returns helper",
                "role": "Answer questions about returns",
                "instructions": (
                    "Help with returns. Keep answers short. Follow attached skills."
                ),
            }
        ),
    )
    ops.agents.add_reference(agent["id"], "skill", skill["id"])
    ops.agents.publish(agent["id"], note="Uses the return checklist")

    thread = cast(ThreadRecord, ops.chat.start(agent["id"]))
    events = [
        cast(ChatEvent, event)
        for event in ops.chat.say(
            thread["id"],
            "I want to return my boots.",
            skill=skill["id"],
            inputs={"order_number": "1182"},
        )
    ]
    done = next(
        event
        for event in reversed(events)
        if event.get("type") == "done" and event.get("message")
    )
    print(done["message"]["skills"])


if __name__ == "__main__":
    main()
