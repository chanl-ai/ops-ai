"""uc-749, api layer: docs/usecases/agents-service/a-skill-needing-a-tool-the-agent-lacks.md.

A part naming a tool the agent does not hold is shown locked and refused with skill_needs_scope."""

from __future__ import annotations

from skills_chat import PLAIN, refusal, skills_stack
from usecase_harness import check, data, finish

with skills_stack() as s:
    skill = s.make_skill({"name": "Renewal opportunity review", **PLAIN, "toolIds": ["salesforce_save_records"]})
    agent = s.make_agent(tool_ids=[])
    rows = data(
        s.api.get("/v1/skills", params={"view": "published", "usableBy": "agent", "agentId": agent}, headers=s.admin)
    )
    row = next((r for r in (rows["data"] if isinstance(rows, dict) else rows) if r["id"] == skill["id"]), {})
    check(
        "1 the menu row is locked and names the tool",
        row.get("locked") is True and "salesforce_save_records" in str(row),
        row,
    )
    status, code = refusal(s.send(s.thread(agent), "Update it", {"skillId": skill["id"], "inputs": {}}))
    check("2 a send naming it is 422 skill_needs_scope", (status, code) == (422, "skill_needs_scope"), (status, code))
finish()
