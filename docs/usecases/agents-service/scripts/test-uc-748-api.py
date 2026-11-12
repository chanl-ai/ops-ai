"""uc-748, api layer: docs/usecases/agents-service/a-reply-over-the-skill-budget-is-refused.md.

A third part picked when two skills already fill the reply, or a part over 6,000 tokens, is refused before any model call."""

from __future__ import annotations

from skills_chat import PREPARE, SALESFORCE, UPDATE, refusal, skills_stack
from usecase_harness import check, finish

BIG = {**PREPARE, "slug": "long-brief", "name": "Long brief", "instructions": "word " * 7000}
with skills_stack() as s:
    thread = s.thread(s.make_agent())
    over = s.make_skill({**SALESFORCE, "name": "Heavy", "parts": [BIG]}, publish=False)
    sent = s.api.post(f"/v1/skills/{over['id']}/publish-requests", json={"note": "use case"}, headers=s.admin)
    check(
        "1 publishing a part over 6,000 tokens is refused", sent.status_code == 422, (sent.status_code, sent.text[:200])
    )
    ok = s.make_skill({**SALESFORCE, "name": "Briefing", "parts": [PREPARE, UPDATE]})
    for part in ("prepare-meeting", "update-opportunity"):
        s.send(thread, "Go", {"skillId": ok["id"], "part": part, "inputs": {"client": "A"}})
    other = s.make_skill({**SALESFORCE, "name": "Second skill", "parts": [PREPARE]})
    status, code = refusal(
        s.send(thread, "Go", {"skillId": other["id"], "part": "prepare-meeting", "inputs": {"client": "A"}})
    )
    check("2 a part past the reply's cap is 422 skill_budget", (status, code) == (422, "skill_budget"), (status, code))
finish()
