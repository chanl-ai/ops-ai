"""uc-745, api layer: docs/usecases/agents-service/no-skills-view-no-menu.md.

A person with the Chat user role (no Skills: view) cannot pick a skill; the send is refused and nothing runs."""

from __future__ import annotations

from skills_chat import PLAIN, refusal, skills_stack
from usecase_harness import check, finish

with skills_stack() as s:
    skill = s.make_skill({"name": "Salesforce", **PLAIN})
    thread = s.thread(s.make_agent(), s.chat_user)
    status, code = refusal(s.send(thread, "Prepare my meeting", {"skillId": skill["id"], "inputs": {}}, s.chat_user))
    check("1 naming a skill without the right is 403 forbidden", (status, code) == (403, "forbidden"), (status, code))
    listed = s.api.get("/v1/skills", params={"view": "published", "usableBy": "agent"}, headers=s.chat_user)
    check("2 the menu's list is refused for the same person", listed.status_code == 403, listed.text[:200])
finish()
