"""uc-744, api layer: docs/usecases/agents-service/update-an-opportunity-from-the-same-skill.md.

A second part of the same skill is picked in the same chat; the first part is carried, not loaded again."""

from __future__ import annotations

from skills_chat import SALESFORCE, skills_stack
from usecase_harness import check, finish

with skills_stack() as s:
    skill = s.make_skill(SALESFORCE)
    thread = s.thread(s.make_agent())
    first = s.send(
        thread,
        "Prepare my meeting",
        {"skillId": skill["id"], "part": "prepare-meeting", "inputs": {"client": "Okafor Family Trust"}},
    )
    check("1 the first part is accepted", first.status_code == 200, first.text[:300])
    res = s.send(
        thread,
        "They agreed to $75,000, move it forward a stage",
        {"skillId": skill["id"], "part": "update-opportunity", "inputs": {"client": "Okafor Family Trust"}},
    )
    check("2 the second part of the same skill is accepted", res.status_code == 200, res.text[:300])
    used = s.last_reply(thread).get("skills", [])
    check(
        "3 the reply names the second part as picked",
        any(x.get("part") == "update-opportunity" and x.get("how") == "picked" for x in used),
        used,
    )
    check(
        "4 the first part is carried, not loaded again",
        any(x.get("part") == "prepare-meeting" and x.get("how") == "carried" for x in used),
        used,
    )
finish()
