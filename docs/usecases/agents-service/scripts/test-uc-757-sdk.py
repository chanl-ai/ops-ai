"""uc-757, sdk layer: docs/usecases/agents-service/a-builder-writes-a-skill-with.md, steps 7 and 8. The same builder
through the Python SDK in sdk/python: a skill with steps, an agent applied from a definition with a brief, the publish
check, the insert and the publish. Platform sign-in (lib/main_chains.py bank_stack); no model is called."""

from __future__ import annotations

import time

from apps_walk import signed_sdk
from brief_steps import brief, confirm_skill, freeze_skill
from main_chains import bank_stack, publish_bank_module
from usecase_harness import check, finish

RUN = int(time.time())

with bank_stack() as s:
    _, read, write = publish_bank_module(
        s.gw, RUN, approval=True, team=s.who["builder"], security=s.who["security"]
    )
    time.sleep(31)  # agents-service keeps each tenant's tool list for 30 seconds
    ops = signed_sdk("builder")

    confirm = ops.skills.create(confirm_skill(RUN, "sdk"))
    ops.skills.publish(confirm["id"], note="use case")
    freeze = ops.skills.create(freeze_skill(RUN, "sdk", read, write, confirm["id"]))
    published = ops.skills.publish(freeze["id"], note="use case")
    steps = ops.skills.get(freeze["id"])["content"]["steps"]
    check(
        "7 the SDK saves a skill with steps and publishes it",
        [s_.get("use", {}).get("kind") for s_ in steps] == ["tool", "skill", "tool"]
        and steps[0]["check"]["by"] == "rule"
        and published.get("publishedVersion") == 1,
        (steps, published.get("publishedVersion")),
    )

    name = f"Freeze desk sdk {RUN}"
    agent = ops.agents.apply(
        {"name": name, "role": "Freezes accounts", "brief": brief(read), "patterns": {"thinking": "low"}}
    )
    aid = str(agent["id"])
    before = ops.agents.publish_check(aid)
    ops.agents.add_reference(aid, "tool", read)
    added = ops.agents.add_reference(aid, "skill", freeze["id"])
    after = ops.agents.publish_check(aid)
    asked = ops.agents.publish(aid, note="use case")
    if asked.get("status") == "pending":
        # A brief's never rules are reviewed by a second person before they go live.
        signed_sdk("approver").raw.agents.reviews_decide_publish_request(asked["id"], {"decision": "approved"})
    live = ops.agents.get(aid)
    check(
        "8 the SDK applies an agent with a brief, adds what it mentions and publishes it",
        agent["promptMode"] == "brief"
        and agent["instructions"].startswith(f"# Who you are\nYou are {name}.")
        and [p["id"] for p in before["problems"]] == [f"tool:{read}"]
        and len(added["added"]) == 3
        and after == {"canRequest": True, "problems": []}
        and live["publishedVersion"] == live["version"],
        (agent.get("promptMode"), before, added, after, live.get("publishedVersion"), live.get("version")),
    )
finish()
