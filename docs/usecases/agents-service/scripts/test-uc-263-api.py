"""uc-263 a typed task opens with task assist when the team turns it on, api layer.

Doc: docs/usecases/agents-service/task-assist.md. ai_steps_stack (platform-service, models-service on the fake
OpenAI, agents service, worker); the task comes from POST /v1/tasks, which runs it as the api_task workflow.
"""

from __future__ import annotations

from typing import Any

import httpx
from ai_steps_stack import OPS, ai_stack, turn_on
from usecase_harness import check, data, finish, until

FACTS = [{"label": "Vendor", "value": "Acme"}, {"label": "New account", "value": "****4410"}]


def post(api: httpx.Client, title: str) -> str:
    res = api.post(
        "/v1/tasks", json={"type": "generic_decision", "params": {"title": title, "facts": FACTS}}, headers=OPS
    )
    return str(data(res)["id"]) if res.status_code == 201 else ""


def regions(api: httpx.Client, task_id: str) -> dict[str, Any]:
    def opened() -> dict[str, Any] | None:
        res = api.get(f"/reviews/{task_id}", headers=OPS)
        return data(res) if res.status_code == 200 and data(res).get("task") else None

    review = until(opened) or {}
    return {r["region"]: r["data"] for r in (review.get("task") or {}).get("regions", [])}


with ai_stack("uc263") as (api, people):
    off = regions(api, post(api, "Change Acme's bank account? UC263-ASSIST"))
    check("1 with task assist off the task opens without help", "header" in off and "assist" not in off, list(off))

    on = turn_on(people, "taskAssist")
    check("2 the team's admin turns task assist on (200)", on.status_code == 200, on.text[:200])
    helped = regions(api, post(api, "Change Acme's bank account? UC263-ASSIST"))
    assist = helped.get("assist") or {}
    check(
        "3 the task opens with its question, summary, doubtful fields and a suggestion, marked AI",
        assist.get("ai") is True
        and assist.get("doubtful") == ["New account"]
        and (assist.get("suggestion") or {}).get("action") == "reject",
        assist,
    )
    check(
        "4 the help sits after the question and before the evidence",
        list(helped)[:3] == ["header", "assist", "facts"],
        list(helped),
    )

    odd = regions(api, post(api, "Open it? UC263-ODD")).get("assist") or {}
    check(
        "5 a suggestion of an action the type does not have is dropped",
        odd.get("question") == "Open it?" and odd.get("suggestion") is None,
        odd,
    )

finish()
