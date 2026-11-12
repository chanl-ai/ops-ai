"""uc-750, api layer: docs/usecases/agents-service/an-admin-limits-the-menu.md.

An agent set to Only attached skills offers and runs only its pinned skills; set to None it refuses every pick."""

from __future__ import annotations

from skills_chat import PLAIN, refusal, skills_stack
from usecase_harness import check, data, finish

with skills_stack() as s:
    pinned = s.make_skill({"name": "Pinned skill", **PLAIN})
    loose = s.make_skill({"name": "Loose skill", **PLAIN})
    agent = s.make_agent("Claims", skill_menu="attached")
    s.api.put(f"/v1/agents/{agent}/skills/{pinned['id']}", json={}, headers=s.admin)
    rows = data(
        s.api.get("/v1/skills", params={"view": "published", "usableBy": "agent", "agentId": agent}, headers=s.admin)
    )
    names = [r["name"] for r in (rows["data"] if isinstance(rows, dict) else rows)]
    check("1 the menu lists only the pinned skill", names == ["Pinned skill"], names)
    status, code = refusal(s.send(s.thread(agent), "Go", {"skillId": loose["id"], "inputs": {}}))
    check(
        "2 a send naming another skill is 422 skill_menu_limit",
        (status, code) == (422, "skill_menu_limit"),
        (status, code),
    )
    off = s.make_agent("Closed", skill_menu="off")
    status, code = refusal(s.send(s.thread(off), "Go", {"skillId": pinned["id"], "inputs": {}}))
    check("3 an agent set to None refuses every pick", (status, code) == (422, "skill_menu_limit"), (status, code))
finish()
