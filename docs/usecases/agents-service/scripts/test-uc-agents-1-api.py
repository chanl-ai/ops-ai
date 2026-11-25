# The use case runner puts docs/usecases/lib (usecase_harness) on the path; pyright alone cannot see it.
# pyright: basic, reportMissingImports=false
"""uc-agents-1 an agent's tools are chosen by app, api layer:
docs/usecases/agents-service/an-agents-tools-are-chosen-by-app.md, steps 1 to 7.

agents-service on the scripted model with its fixture tools, which belong to several systems. A builder's new agent
holds no tool. The builder finds an app by the name of one of its tools, lists that app's tools, grants all of them in
one save, and reads the app back with every tool counted and marked as granted. An app id nobody has answers 404.
The agent is then granted a second agent, which is paused, and agents-service is started again with a tools-service
nothing answers: both times every tool the agent holds is still named by its lists, so a person can remove it. No model
is called."""

from __future__ import annotations

import secrets
from collections import Counter
from typing import Any

import httpx
from usecase_harness import TEAM, agents, check, data, finish, free_port, save_agent


def listed_grants(api: httpx.Client, agent_id: str) -> tuple[list[str], list[str]]:
    """The tools the agent holds, and the ones its page can draw: each app's granted tools, then the grants the agent's
    own read says are no longer offered."""
    seen: dict[str, Any] = data(api.get(f"/v1/agents/{agent_id}", headers=TEAM)) or {}
    path = f"/v1/agents/{agent_id}/tool-apps"
    apps = (data(api.get(path, params={"granted": "true", "limit": 100}, headers=TEAM)) or {}).get("data") or []
    drawn = [str(t) for t in seen.get("staleToolIds") or []]
    for a in apps:
        tools = api.get(f"{path}/{a['id']}/tools", params={"granted": "true", "limit": 100}, headers=TEAM)
        drawn += [str(t["id"]) for t in (data(tools) or {}).get("data") or []]
    return sorted(str(t) for t in seen.get("toolIds") or []), sorted(drawn)


with agents() as api:
    made = api.post("/v1/agents", json={"name": f"Tools by app {secrets.token_hex(2)}", "role": "Reads"}, headers=TEAM)
    assert made.status_code == 201, made.text[:300]
    agent = data(made)["id"]
    apps_path = f"/v1/agents/{agent}/tool-apps"

    # The app to choose: the system that holds the most of the tools this stack offers.
    listed = data(api.get("/v1/tools", params={"pageSize": 200}, headers=TEAM))["data"]
    own = [t for t in listed if not str(t["id"]).startswith(("workflow:", "agent:"))]
    system = Counter(str(t["server"]) for t in own).most_common(1)[0][0]
    wanted = sorted(str(t["id"]) for t in own if t["server"] == system)
    assert len(wanted) > 1, f"the fixture offers one tool under {system}"

    found = api.get(apps_path, params={"search": wanted[0]}, headers=TEAM)
    hits: list[dict[str, Any]] = (data(found) or {}).get("data") or []
    app: dict[str, Any] = next((a for a in hits if a.get("name") == system), {})
    check(
        "1 searching a tool's name finds its app, with the tool listed under it and nothing granted",
        found.status_code == 200
        and [m["id"] for m in app.get("matches") or []] == [wanted[0]]
        and app.get("toolsGranted") == 0
        and app.get("toolsOffered") == len(wanted),
        {"http": found.status_code, "apps": [a.get("name") for a in hits], "app": app},
    )

    tools_path = f"{apps_path}/{app.get('id')}/tools"
    offered = api.get(tools_path, params={"limit": 100}, headers=TEAM)
    rows: list[dict[str, Any]] = (data(offered) or {}).get("data") or []
    check(
        "2 the app lists its own tools and no other system's, none granted yet",
        offered.status_code == 200
        and sorted(r["id"] for r in rows) == wanted
        and not any(r["granted"] for r in rows),
        {"http": offered.status_code, "tools": [(r.get("id"), r.get("granted")) for r in rows], "wanted": wanted},
    )

    saved = save_agent(api, agent, {"toolIds": wanted}, headers=TEAM)
    check(
        "3 every tool of the app is granted in one save",
        saved.status_code == 200 and sorted((data(saved) or {}).get("toolIds") or []) == wanted,
        f"{saved.status_code} {saved.text[:300]}",
    )

    held = (data(api.get(apps_path, params={"granted": "true", "limit": 100}, headers=TEAM)) or {}).get("data") or []
    after = (data(api.get(tools_path, params={"limit": 100}, headers=TEAM)) or {}).get("data") or []
    check(
        "4 the agent's apps are that one app, with every tool counted and marked as granted",
        [(a["name"], a["toolsGranted"], a["toolsOffered"]) for a in held] == [(system, len(wanted), len(wanted))]
        and sorted(r["id"] for r in after if r["granted"]) == wanted,
        {"apps": [(a.get("name"), a.get("toolsGranted")) for a in held], "granted": [r.get("granted") for r in after]},
    )

    unknown = api.get(f"{apps_path}/app_nobody_has/tools", headers=TEAM)
    check(
        "5 an app nobody has answers 404 not_found, while the app of step 2 answered",
        unknown.status_code == 404
        and (unknown.json().get("error") or {}).get("code") == "not_found"
        and offered.status_code == 200,
        f"{unknown.status_code} {unknown.text[:200]}",
    )

    # A second agent, live, granted to the first as a tool and then paused: it is no longer offered.
    helper = data(api.post("/v1/agents", json={"name": f"Helper {secrets.token_hex(2)}", "role": "Helps"}, headers=TEAM))
    live = api.post(
        f"/v1/agents/{helper['id']}/publish-requests", json={"version": helper["version"], "note": "x"}, headers=TEAM
    )
    assert live.status_code == 201, live.text[:300]
    grant = f"agent:{helper['id']}"
    both = save_agent(api, agent, {"toolIds": [*wanted, grant]}, headers=TEAM)
    assert both.status_code == 200, both.text[:300]
    paused = api.post(f"/v1/agents/{helper['id']}/paused", json={"paused": True}, headers=TEAM)
    assert paused.status_code == 200, paused.text[:300]
    options = data(api.get("/v1/tools/options", params={"ids": [grant]}, headers=TEAM)) or {}
    held, drawn = listed_grants(api, agent)
    check(
        "6 a granted agent that was paused is no longer offered, and is still listed among the tools the agent holds",
        not options.get("data") and grant in held and drawn == held,
        {"offered": options.get("data"), "held": held, "listed": drawn},
    )

# The same database, with a tools-service nothing answers: the agent's operations cannot be named by tools-service.
with agents(gateway_url=f"http://127.0.0.1:{free_port()}") as api:
    apps_read = api.get(f"/v1/agents/{agent}/tool-apps", params={"granted": "true"}, headers=TEAM)
    held, drawn = listed_grants(api, agent)
    check(
        "7 with tools-service out of reach, every tool the agent holds is still listed",
        apps_read.status_code == 200 and len(held) == len(wanted) + 1 and drawn == held,
        {"http": apps_read.status_code, "held": held, "listed": drawn},
    )

finish()
