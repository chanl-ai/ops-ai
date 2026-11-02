"""uc-616, api layer: docs/usecases/tools-service/usage-shows-only-this-team-s.md, stories S1-S3 (steps 1-4), group G
of an earlier change. The Apps stack (docs/usecases/lib/apps_walk.py); each run's call is made as agents-service makes it. A check
whose behaviour is not built names the task it waits on. No model call."""

from __future__ import annotations

from typing import Any

from apps_walk import apps_stack
from usecase_harness import check, data, finish


def call_id(r: Any) -> str:
    return str((data(r) or {}).get("callId") or "") if r.status_code == 200 else ""


with apps_stack() as w:
    key = {"credentials": {"key": w.m["secrets"]["key"]}}

    # 1. Both teams use the header-key desk.
    w.turn_on("admin", "test.header-key", **key)
    w.turn_on("platform", "test.header-key", **key)
    ours = w.call("header_key_get_record", args={"id": "rec-1042"})
    theirs = w.call("header_key_get_record", team="team_platform", args={"id": "rec-1042"})
    check(
        "1 a run in each team reads a record (200)",
        bool(call_id(ours) and call_id(theirs)),
        (ours.text[:200], theirs.text[:200]),
    )

    # 2. Each team's Usage holds only its own calls.
    def usage(role: str, **params: str) -> list[dict[str, Any]]:
        r = w.kept(w.gw.get("/v1/executions", params=params or None, headers=w.who[role]))
        return list((data(r) or {}).get("data") or []) if r.status_code == 200 else [{"http": r.status_code}]

    mine, platform = usage("admin"), usage("platform")
    check(
        "2 Priya's Usage lists team_ops's call and not team_platform's, and Wanjiru's the reverse",
        call_id(ours) in [r.get("id") for r in mine]
        and call_id(theirs) not in [r.get("id") for r in mine]
        and call_id(theirs) in [r.get("id") for r in platform]
        and call_id(ours) not in [r.get("id") for r in platform],
        {"mine": mine[:3], "platform": platform[:3]},
    )

    # 3. Whom each call ran as: Team account, or the person a run acted for.
    person = w.turn_on("admin", "test.person-key", signIn="person")
    james_key = w.m["person_keys"]["james"]
    w.kept(
        w.gw.put(
            f"/v1/me/connections/{person}/credentials",
            json={"environment": "production", "credentials": {"key": james_key}},
            headers=w.who["builder"],
        )
    )
    as_james = w.call("person_key_get_record", args={"id": "rec-1042"}, acting_for="j.richardson@harborpine.example")
    rows = {r.get("id"): r for r in usage("admin")}
    team_row, james_row = rows.get(call_id(ours)) or {}, rows.get(call_id(as_james)) or {}
    check(
        "3 the team account's call ran as the team, and the call a run made for James ran as James",
        (team_row.get("runAs") or {}).get("kind") == "team"
        and james_row.get("runAs") == {"kind": "person", "email": "j.richardson@harborpine.example"},
        {"team": team_row.get("runAs"), "james": james_row.get("runAs"), "call": as_james.text[:200]},
    )

    # 4. Usage narrows to one app.
    page = data(w.gw.get("/v1/apps/plugin:test.header-key", headers=w.who["admin"])) or {}
    module = str(((page.get("card") or {}).get("moduleIds") or ["mod_missing"])[0])
    one_app = usage("admin", moduleId=module)
    check(
        "4 Usage for the header-key desk lists only its calls",
        bool(one_app) and all(r.get("app") == "Header key desk" for r in one_app),
        one_app[:3],
    )

finish()
