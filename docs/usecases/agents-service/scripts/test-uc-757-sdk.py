"""uc-757, sdk layer: docs/usecases/agents-service/a-builder-writes-a-skill-with.md, steps 7 and 8. The same builder
through the Python SDK in sdk/python: a skill with steps, an agent applied from a definition with a brief, the publish
check, the insert and the publish. Platform sign-in (lib/main_chains.py bank_stack); no model is called."""

from __future__ import annotations

import time

from apps_walk import signed_sdk
from brief_steps import SECTION_HEADINGS, SECTIONS, brief, confirm_skill, freeze_skill, headings, sections_brief
from main_chains import bank_stack, publish_bank_module
from ops_ai.errors import OpsError
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
        and [(s_.get("check") or {}).get("by") for s_ in steps] == ["rule", None, "rule"]
        and published.get("publishedVersion") == 1,
        (steps, published.get("publishedVersion")),
    )

    # A step that changes something is refused without a rule check, and a tool a sentence names is not run.
    body = freeze_skill(RUN, "sdk", read, write, confirm["id"])
    bare = {**body, "name": f"Bare freeze sdk {RUN}", "steps": [*body["steps"][:2], {"do": "Freeze it.", "use": body["steps"][2]["use"]}]}
    refused: tuple[int | None, str | None] = (None, None)
    try:
        ops.skills.create(bare)
    except OpsError as error:
        refused = (error.status, error.code)
    named = ops.skills.create({**body, "name": f"Named freeze sdk {RUN}", "steps": [{"do": f"Read it with @tool:{read}."}]})
    stops = [(p["kind"], p["id"]) for p in named["publishCheck"]["problems"]]
    check(
        "7 the SDK is refused a write step with no rule check, and a tool a sentence only names blocks the publish",
        refused == (400, "write_needs_rule") and named["content"]["steps"][0].get("use") is None and stops == [("bad_step", f"tool:{read}")],
        (refused, named["content"]["steps"], stops),
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

    # 26. The same sections through the SDK: the definition's `brief.sections` field, read back, and the prompt.
    desk = ops.agents.apply(
        {"name": f"Sections desk sdk {RUN}", "role": "Freezes accounts", "brief": sections_brief(SECTIONS)}
    )
    replied = (ops.agents.get(str(desk["id"])).get("brief") or {}).get("sections")
    shown = ops.raw.agents.agents_agent_prompt(str(desk["id"]))["text"]
    check(
        "26 the SDK applies a brief with Tone and a custom section, reads both back and the prompt has them in order",
        replied == [{**SECTIONS[0]}, {"kind": "tone", "name": "Tone", "text": "Calm and plain."}]
        and headings(shown) == SECTION_HEADINGS
        and shown.rstrip().endswith("- Never promise when a freeze will be lifted."),
        (replied, headings(shown)),
    )
finish()
