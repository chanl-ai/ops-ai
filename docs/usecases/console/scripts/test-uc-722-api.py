"""uc-722 the console offers pages by what a person may open, api layer: docs/usecases/console/console-areas.md.
Two server-side facts the sidebar's areas depend on: the fixture people hold exactly the cells the areas are built
from, and the tool-call page can show one call by its id (the chat's "Open call" link)."""

from __future__ import annotations

import time
from typing import Any

from usecase_harness import agents, check, data, finish, platform, service_headers, tools

PASSWORD = "northfield-demo"
THREAD = f"uc722_{int(time.time())}"
CONTEXT = {"thread": THREAD, "act": "agent:dispute_triage"}


def held(view: dict[str, Any], team: str) -> set[str]:
    rows = next((t["permissions"] for t in view.get("teams", []) if t["teamId"] == team), [])
    return {f"{p['area']}.{p['action']}" for p in rows}


def cells(api: Any, email: str, team: str) -> set[str]:
    r = api.post("/v1/auth/sign-in", json={"email": email, "password": PASSWORD})
    token = data(r)["token"] if r.status_code == 200 else ""
    view = data(api.get("/v1/me/permissions", headers={"Authorization": f"Bearer {token}", "X-Team-Id": team}))
    return held(view, team)


with platform() as (api, _internal):
    lena = cells(api, "l.brandt@harborpine.example", "team_ops")
    # Fixture guard: green by design, it only proves the chat-only person exists and holds chat alone.
    check(
        "1 the chat-only person holds chat and no page's view cell",
        "chat.run" in lena and not any(c.endswith(".view") and not c.startswith("chat.") for c in lena),
        sorted(lena),
    )

    tomas_ops, tomas_platform = (
        cells(api, "t.reyes@harborpine.example", "team_ops"),
        cells(api, "t.reyes@harborpine.example", "team_platform"),
    )
    check(
        "2 the two-team person builds in Operations and only chats in Platform",
        "agents.view" in tomas_ops
        and "agents.edit" in tomas_ops
        and "chat.run" in tomas_platform
        and "agents.view" not in tomas_platform,
        {"ops": len(tomas_ops), "platform": sorted(tomas_platform)},
    )

    ravi = cells(api, "r.menon@harborpine.example", "team_ops")
    maya = cells(api, "m.okafor@harborpine.example", "team_ops")
    # Activity is offered on activity.view (the cell the tool-call service checks), which a viewer does not hold.
    check(
        "3 a viewer lacks activity.view and a reviewer holds it",
        "activity.view" not in ravi and "activity.view" in maya,
        {"ravi": "activity.view" in ravi, "maya": "activity.view" in maya},
    )

with agents(), tools() as gw:

    def call(step: str) -> str:
        res = gw.post(
            "/v1/calls",
            json={
                "tool": "get_loan_account",
                "input": {"loanAccountId": "LN-0048213"},
                "key": step,
                "runContext": {**CONTEXT, "step": step},
            },
            headers=service_headers("tools"),
        )
        check(f"call {step} runs", res.status_code == 200, res.text[:200])
        return step

    call("c1")
    call("c2")
    rows = data(gw.get("/v1/executions", params={"thread": THREAD, "pageSize": 10})).get("data", [])
    by_step = {r.get("step"): r["id"] for r in rows}
    check("4 setup: two calls are logged in one thread", sorted(by_step) == ["c1", "c2"], sorted(by_step))
    one = gw.get("/v1/executions", params={"call": by_step.get("c1"), "pageSize": 10})
    listed = data(one).get("data", []) if one.status_code == 200 else []
    # Non-vacuous: without the filter both calls of the company's log come back, which is what the page shows today.
    check(
        "5 the call filter returns exactly the one call asked for",
        one.status_code == 200 and [r["id"] for r in listed] == [by_step.get("c1")],
        {"status": one.status_code, "ids": [r.get("id") for r in listed]},
    )
    none = gw.get("/v1/executions", params={"call": "call_that_does_not_exist", "pageSize": 10})
    check(
        "6 an unknown call id returns no rows, not every row",
        none.status_code == 200 and data(none).get("data") == [],
        none.text[:200],
    )

finish()
