# The use case runner puts docs/usecases/lib (usecase_harness) on the path; pyright alone cannot see it.
# pyright: basic, reportMissingImports=false
"""uc-agents-2 an agent is applied from a spec file, api layer:
docs/usecases/agents-service/an-agent-is-applied-from-a-spec-file.md, steps 1 to 7.

agents-service on the scripted model with its fixture tools and knowledge bases. A developer makes an agent, checks a
spec file for an insurance claims desk, applies it and reads it back equal; a copy that breaks two rules is refused
with each field's path and saves nothing; a changed copy shows one change; a copy made from an older version is
refused. No model is called."""

from __future__ import annotations

import secrets
from typing import Any

from usecase_harness import TEAM, agents, check, data, finish

with agents() as api:
    name = f"Claims intake {secrets.token_hex(2)}"
    made = api.post("/v1/agents", json={"name": name, "role": "Drafted"}, headers=TEAM)
    assert made.status_code == 201, made.text[:300]
    agent = str(data(made)["id"])
    path = f"/v1/agents/{agent}/spec"

    first = api.get(path, headers=TEAM)
    view: dict[str, Any] = data(first) or {}
    check(
        "1 a new agent reads as a spec document with its version and digest",
        first.status_code == 200 and view.get("version") == 1 and (view.get("spec") or {}).get("name") == name,
        f"{first.status_code} {first.text[:300]}",
    )

    listed = data(api.get("/v1/tools", params={"pageSize": 200}, headers=TEAM))["data"]
    tools = sorted(str(t["id"]) for t in listed if not str(t["id"]).startswith(("workflow:", "agent:")))[:2]
    kbs = [str(k["id"]) for k in data(api.get("/v1/knowledge-bases/refs", headers=TEAM)) or []][:1]
    spec: dict[str, Any] = {
        "apiVersion": "ops.ai/v2",
        "name": name,
        "role": "Opens insurance claims from a policyholder's first report and asks for what is missing.",
        "instructions": "Ask for the policy number first. Never say whether a claim will be paid.",
        "loop": {"kind": "supervisor", "maxSteps": 12},
        "toolIds": tools,
        "collections": kbs,
        "limits": {"budget": {"defaultUsd": 0.4, "ceilingUsd": 1.5}},
    }
    checked = api.post("/v1/agents/spec/validate", json={"spec": spec}, headers=TEAM)
    found: dict[str, Any] = data(checked) or {}
    check(
        "2 the file validates, with a summary of its loop and tools",
        checked.status_code == 200
        and found.get("ok") is True
        and found.get("summary", {}).get("loopKind") == "supervisor"
        and found.get("summary", {}).get("tools") == len(tools),
        {"http": checked.status_code, "check": found},
    )

    body = {"spec": spec, "baseVersion": view.get("version"), "baseDigest": view.get("digest")}
    applied = api.put(path, json=body, headers=TEAM)
    back: dict[str, Any] = data(api.get(path, headers=TEAM)) or {}
    agent_read: dict[str, Any] = data(api.get(f"/v1/agents/{agent}", headers=TEAM)) or {}
    check(
        "3 the applied file reads back equal, and the agent's page reads the same version",
        applied.status_code == 200
        and back.get("spec") == {**spec, "id": agent}
        and agent_read.get("digest") == back.get("digest"),
        {"http": applied.status_code, "applied": applied.text[:300], "back": back.get("spec")},
    )

    bad = {**spec, "toolIds": [*tools, "claims.no_such_tool"], "loop": {"kind": "supervisor", "maxStepz": 4}}
    refused_check: dict[str, Any] = data(api.post("/v1/agents/spec/validate", json={"spec": bad}, headers=TEAM)) or {}
    paths = sorted(str(p["path"]) for p in refused_check.get("problems") or [])
    check(
        "4 a copy with an unknown field is refused at that field's path",
        refused_check.get("ok") is False and paths == ["/loop/maxStepz"],
        refused_check,
    )
    del bad["loop"]["maxStepz"]
    refused_check = data(api.post("/v1/agents/spec/validate", json={"spec": bad}, headers=TEAM)) or {}
    check(
        "4b with the field fixed, the tool nobody offers is refused at its index",
        [p["path"] for p in refused_check.get("problems") or []] == [f"/toolIds/{len(tools)}"],
        refused_check,
    )

    newest = {"spec": bad, "baseVersion": back.get("version"), "baseDigest": back.get("digest")}
    put_bad = api.put(path, json=newest, headers=TEAM)
    after: dict[str, Any] = data(api.get(path, headers=TEAM)) or {}
    error: dict[str, Any] = put_bad.json().get("error") or {}
    check(
        "5 applying the bad copy answers 422 spec_invalid with the path, and saves nothing",
        put_bad.status_code == 422
        and error.get("code") == "spec_invalid"
        and [p["path"] for p in (error.get("details") or {}).get("problems") or []] == [f"/toolIds/{len(tools)}"]
        and (after.get("version"), after.get("digest")) == (back.get("version"), back.get("digest")),
        {"http": put_bad.status_code, "error": error},
    )

    raised = {**spec, "limits": {"budget": {"defaultUsd": 0.4, "ceilingUsd": 3.0}}}
    compared = api.post(f"{path}/diff", json={"spec": raised}, headers=TEAM)
    changes = (data(compared) or {}).get("changes") or []
    check(
        "6 the diff names the one change, the budget ceiling",
        compared.status_code == 200
        and [(c["op"], c["path"], c["before"], c["after"]) for c in changes]
        == [("replace", "/limits/budget/ceilingUsd", 1.5, 3.0)],
        {"http": compared.status_code, "changes": changes},
    )

    stale = api.put(path, json={**body, "spec": raised}, headers=TEAM)
    check(
        "7 a file made from the first version is refused as stale",
        stale.status_code == 409 and (stale.json().get("error") or {}).get("code") == "stale_base",
        f"{stale.status_code} {stale.text[:300]}",
    )

finish()
