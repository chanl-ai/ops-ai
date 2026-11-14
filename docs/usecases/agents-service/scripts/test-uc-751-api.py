"""uc-751, api layer: docs/usecases/agents-service/evals-keep-saved-cases-and-runs.md. A builder saves test cases on an
agent and runs them twice; the Evals page's three reads list the suite and both runs; a viewer reads but cannot save; a
member of a second team sees nothing of it. Platform sign-in and agents-service on the scripted model."""

from __future__ import annotations

from typing import Any

from usecase_harness import (
    AGENTS_PORT,
    PLATFORM_INTERNAL_PORT,
    PLATFORM_PORT,
    agents,
    as_role,
    check,
    data,
    finish,
    platform,
)

AUTH = {
    "OPS_AUTH_MODE": "platform",
    "OPS_PLATFORM_URL": f"http://127.0.0.1:{PLATFORM_PORT}",
    "OPS_PLATFORM_INTERNAL_PORT": str(PLATFORM_INTERNAL_PORT),
}
AGENT = "ag_branch"
CASES = {
    "cases": [
        {"name": "Greets and offers help", "input": "Hello", "checks": [{"type": "reply_contains", "text": "help"}]},
        {"name": "Looks up the account", "input": "My balance?", "checks": [{"type": "calls_tool", "tool": "lookup_account"}]},
    ]
}


def read(api: Any, tab: str, who: dict[str, str]) -> dict[str, Any]:
    r = api.get(f"/v1/assurance/{tab}", headers=who)
    return {"status": r.status_code, **(r.json().get("data") or {})}


with platform() as (identity, _internal), agents(env=AUTH) as api:
    builder, viewer = as_role(identity, "builder"), as_role(identity, "viewer")
    outsider = as_role(identity, "platform")

    saved = api.put(f"/v1/agents/{AGENT}/eval-cases", json=CASES, headers=builder)
    check("1 a builder saves two test cases on an agent (200)", saved.status_code == 200 and len(data(saved)["cases"]) == 2, saved.text[:200])

    first = api.post(f"/v1/agents/{AGENT}/eval-runs", headers=builder)
    second = api.post(f"/v1/agents/{AGENT}/eval-runs", headers=builder)
    ids = [data(r).get("id") for r in (first, second)]
    check("2 running the saved cases twice keeps two runs, not one", first.status_code == second.status_code == 200 and len(set(ids)) == 2, ids)

    runs = read(api, "runs", viewer)
    check(
        "3 a viewer reads both runs on the Runs tab, newest first",
        runs["status"] == 200 and [r["id"] for r in runs["data"]] == ids[::-1] and runs["data"][0]["asset"]["name"],
        [r["id"] for r in runs.get("data", [])],
    )

    suites = read(api, "suites", viewer)
    suite = (suites.get("data") or [{}])[0]
    check(
        "4 the Suites tab lists the agent with its two cases, and its counts equal its rows",
        suite.get("cases") == 2 and suites["tabCounts"] == {"suites": 1, "runs": 2, "gates": suites["tabCounts"]["gates"]},
        {"suite": suite.get("id"), "counts": suites.get("tabCounts")},
    )

    refused = api.put(f"/v1/agents/{AGENT}/eval-cases", json=CASES, headers=viewer)
    check("5 a viewer cannot save cases (403)", refused.status_code == 403, refused.status_code)

    theirs = read(api, "suites", outsider)
    blocked = api.put(f"/v1/agents/{AGENT}/eval-cases", json=CASES, headers=outsider)
    check(
        "6 a member of another team sees no suite or run of this team and cannot touch its cases (404)",
        theirs["status"] == 200 and theirs["data"] == [] and theirs["tabCounts"]["runs"] == 0 and blocked.status_code == 404,
        {"rows": len(theirs.get("data", [])), "put": blocked.status_code},
    )

    check(
        "7 evidence and judges are not offered: no count, and their routes answer 404",
        set(suites["tabCounts"]) == {"suites", "runs", "gates"} and api.get("/v1/assurance/evidence", headers=viewer).status_code == 404,
        suites["tabCounts"],
    )

finish()
