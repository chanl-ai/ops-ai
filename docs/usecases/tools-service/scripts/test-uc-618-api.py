"""uc-618, api layer: docs/usecases/tools-service/turning-an-app-off-names-its.md, stories S1-S3 (steps 1-4), group K
of an earlier change. The Apps stack (docs/usecases/lib/apps_walk.py) with agents-service beside tools-service, so an agent can
hold the app's tool. A check whose behaviour is not built names the task it waits on. No model call."""

from __future__ import annotations

from apps_walk import AUTH, app_path, apps_stack, target
from usecase_harness import agents, check, data, finish, until

APP = "plugin:test.header-key"
KEYED = "plugin:test.person-key"

with apps_stack() as w, agents(gateway_url=str(w.gw.base_url).rstrip("/"), env=AUTH) as api:
    admin, builder = w.who["admin"], w.who["builder"]

    # 1. Turning the app off first names the agent that uses its tool.
    account = w.turn_on("admin", "test.header-key", credentials={"key": w.m["secrets"]["key"]})
    made = api.post("/v1/agents", json={"name": "Records helper", "role": "Reads records"}, headers=builder)
    agent_id = str((data(made) or {}).get("id") or "")
    api.patch(f"/v1/agents/{agent_id}", json={"toolIds": ["header_key_get_record"]}, headers=builder)
    users = w.kept(w.gw.get("/v1/plugins/test.header-key/team/users", headers=admin))
    check(
        "1 before turning the desk off, its users name the agent Records helper and the tool it holds",
        made.status_code == 201
        and users.status_code == 200
        and any(
            u.get("name") == "Records helper" and "header_key_get_record" in (u.get("tools") or [])
            for u in (data(users) or {}).get("agents") or []
        ),
        (target("P1"), made.status_code, users.status_code, users.text[:200]),
    )

    # 2. Turned off, the desk reads off for the team.
    off = w.kept(w.gw.put("/v1/plugins/test.header-key/team", json={"enabled": False}, headers=admin))
    after = data(w.kept(w.gw.get(app_path(APP), headers=admin))) or {}
    check(
        "2 turned off, the desk reads off for the team",
        off.status_code == 200 and (after.get("card") or {}).get("plugin", {}).get("teamOn") is False,
        (off.status_code, off.text[:200]),
    )

    # 3. A person removed from the team loses their own account on its apps.
    keyed = w.turn_on("admin", "test.person-key", signIn="person")
    james_key = w.m["person_keys"]["james"]
    w.gw.put(
        f"/v1/me/connections/{keyed}/credentials",
        json={"environment": "production", "credentials": {"key": james_key}},
        headers=builder,
    )
    before = (data(w.gw.get(app_path(KEYED), headers=admin)) or {}).get("peopleCount")
    members = data(w.api.get("/v1/settings/members", headers=admin)) or {}
    rows = members.get("data") if isinstance(members, dict) else members
    james = next((m for m in rows or [] if m.get("email") == "j.richardson@harborpine.example"), {})
    removed = w.api.post("/v1/settings/members/delete", json={"ids": [james.get("id")]}, headers=admin)
    # platform-service's relay carries the removal to tools-service a moment later.
    until(lambda: (data(w.gw.get(app_path(KEYED), headers=admin)) or {}).get("peopleCount") == 0, timeout=30)
    later = (data(w.gw.get(app_path(KEYED), headers=admin)) or {}).get("peopleCount")
    check(
        "3 James removed from team_ops loses his account on the person-key desk",
        before == 1 and removed.status_code == 200 and later == 0,
        (target("S14"), {"before": before, "removed": removed.text[:200], "after": later}),
    )

    # 4. Replace puts a new key on the same team account.
    w.turn_on("admin", "test.header-key", credentials={"key": "wrong-key-0000"})
    broken = w.call("header_key_get_record", args={"id": "rec-1042"})
    replaced = w.turn_on("admin", "test.header-key", credentials={"key": w.m["secrets"]["key"]})
    works = w.call("header_key_get_record", args={"id": "rec-1042"})
    record = ((data(works) or {}).get("output") or {}).get("record") or {}
    check(
        "4 Replace keeps the team account's id and the next call reads the record",
        "401" in broken.text and replaced == account and record.get("id") == "rec-1042",
        {"account": (account, replaced), "works": works.text[:200]},
    )

finish()
