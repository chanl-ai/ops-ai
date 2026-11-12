"""uc-747, api layer: docs/usecases/agents-service/a-missing-input-stops-the-send.md.

A part with a required input and no value refuses the send before any model call."""

from __future__ import annotations

from skills_chat import SALESFORCE, refusal, skills_stack
from usecase_harness import check, finish

with skills_stack() as s:
    skill = s.make_skill(SALESFORCE)
    thread = s.thread(s.make_agent())
    res = s.send(thread, "They agreed to $75,000", {"skillId": skill["id"], "part": "update-opportunity", "inputs": {}})
    status, code = refusal(res)
    check(
        "1 a send with no Client is 422 missing_input",
        (status, code) == (422, "missing_input"),
        (status, code, res.text[:200]),
    )
    check("2 the refusal names the input", "client" in res.text.lower(), res.text[:200])
finish()
