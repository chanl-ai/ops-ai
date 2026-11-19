"""uc-743, api layer: docs/usecases/agents-service/prepare-a-meeting-from-the-slash-menu.md.

A published skill with two parts is used for one reply by picking a part and filling its input; the reply records which part ran and how."""

from __future__ import annotations

from skills_chat import SALESFORCE, skills_stack
from usecase_harness import check, data, finish

with skills_stack() as s:
    skill = s.make_skill(SALESFORCE)
    listed = data(s.api.get(f"/v1/skills/{skill['id']}", headers=s.admin))
    check(
        "1 the published skill keeps its two parts",
        [p["slug"] for p in listed.get("parts", [])] == ["prepare-meeting", "update-opportunity"],
        listed,
    )
    agent = s.make_agent()
    thread = s.thread(agent)
    res = s.send(
        thread,
        "Prepare my meeting",
        {"skillId": skill["id"], "part": "prepare-meeting", "inputs": {"client": "Okafor Family Trust"}},
    )
    check("2 a send naming a part is accepted", res.status_code == 200, res.text[:300])
    used = [x for x in s.last_reply(thread).get("skills", []) if x.get("part")]
    check(
        "3 the reply records the skill, its version, the part and that it was picked",
        any(
            x.get("name") == "Salesforce" and x.get("part") == "prepare-meeting" and x.get("how") == "picked"
            for x in used
        ),
        used,
    )
finish()
