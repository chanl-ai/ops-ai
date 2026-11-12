"""uc-746, api layer: docs/usecases/agents-service/only-published-skills-in-the-menu.md.

A skill with only a draft and a retired skill are neither listed for the menu nor sendable."""

from __future__ import annotations

from skills_chat import PLAIN, refusal, skills_stack
from usecase_harness import check, data, finish

with skills_stack() as s:
    draft = s.make_skill({"name": "Claims intake", **PLAIN}, publish=False)
    retired = s.make_skill({"name": "Day-one checklist", **PLAIN})
    s.api.post(f"/v1/skills/{retired['id']}/deprecate", json={"reason": "replaced"}, headers=s.admin)
    rows = data(s.api.get("/v1/skills", params={"view": "published", "usableBy": "agent"}, headers=s.admin))
    names = [r["name"] for r in (rows["data"] if isinstance(rows, dict) else rows)]
    check(
        "1 neither the draft nor the retired skill is listed",
        "Claims intake" not in names and "Day-one checklist" not in names,
        names,
    )
    thread = s.thread(s.make_agent())
    for label, sid in (("draft", draft["id"]), ("retired", retired["id"])):
        status, code = refusal(s.send(thread, "Use it", {"skillId": sid, "inputs": {}}))
        check(
            f"2 a send naming the {label} skill is 422 skill_not_published",
            (status, code) == (422, "skill_not_published"),
            (status, code),
        )
finish()
