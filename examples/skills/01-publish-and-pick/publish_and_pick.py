"""Publish a skill, give it to an agent, and pick it for one reply."""

from ops_ai import OpsAI


def main() -> None:
    ops = OpsAI()

    # Create a reusable procedure, then publish a version agents can attach.
    skill = ops.skills.create(
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
    )
    ops.skills.publish(skill["id"], note="First version")

    # The agent may only pick skills on its reference list.
    agent = ops.agents.apply(
        {
            "name": "Returns helper",
            "role": "Answer questions about returns",
            "instructions": (
                "Help with returns. Keep answers short. Follow attached skills."
            ),
        }
    )
    ops.agents.add_reference(agent["id"], "skill", skill["id"])
    ops.agents.publish(agent["id"], note="Uses the return checklist")

    # One chat turn: force this skill and supply its input.
    thread = ops.chat.start(agent["id"])
    events = list(
        ops.chat.say(
            thread["id"],
            "I want to return my boots.",
            skill=skill["id"],
            inputs={"order_number": "1182"},
        )
    )
    done = next(
        event
        for event in reversed(events)
        if event.get("type") == "done" and event.get("message")
    )
    print(done["message"]["skills"])


if __name__ == "__main__":
    main()
