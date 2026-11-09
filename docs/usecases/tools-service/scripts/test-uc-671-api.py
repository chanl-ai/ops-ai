"""uc-671, api layer: docs/usecases/tools-service/connectors-for-people.md, stories S12-S14 (steps 1-7), the which-account question in step 3.

The Apps stack of docs/usecases/lib/apps_walk.py: platform-service with the seed's own roles, tools-service with the test
plugins installed, and the fake system whose sign-in names each person in its id token. Person desk (test.person) signs
in as each person. No model call."""

from __future__ import annotations

from typing import Any

from apps_walk import apps_stack, ops_cli, signed_sdk
from usecase_harness import check, data, finish

APP = "plugin:test.person"
PRIYA = "p.shah@harborpine.example"


def own_sign_in(w: Any, role: str, account: str, user: str) -> tuple[int, str]:
    """A person's browser through the fake's sign-in page, for their own sign-in on `account`."""
    started = w.kept(
        w.gw.post(f"/v1/apps/{APP}/accounts/{account}/sign-in", headers=w.who[role], json={"account": "self"})
    )
    url = (data(started) or {}).get("authorizeUrl", "") if started.status_code == 200 else ""
    back = w.m["sign_in"](url, user) if url else {}
    done = w.kept(
        w.gw.post(
            "/v1/sign-ins/complete",
            headers=w.who[role],
            json={"state": back.get("state", ""), "code": back.get("code", "")},
        )
    )
    return done.status_code, (started.text if started.status_code != 200 else done.text)[:300]


def mine(w: Any, role: str) -> dict[str, dict[str, Any]]:
    r = w.kept(w.gw.get("/v1/me/connections", headers=w.who[role]))
    return {str(c["appId"]): c for c in data(r) or []} if r.status_code == 200 else {}


# A person's sign-in returns to the console, so its address is set.
with apps_stack({"OPS_CONSOLE_URL": "https://console.acme.test"}) as w:
    client = w.credential("admin", "test.person", "multi-app", w.m["clients"]["multi-app"])
    first = w.turn_on("admin", "test.person", signIn="person", credentialId=client)
    second_made = w.kept(
        w.gw.post(f"/v1/apps/{APP}/accounts", json={"name": "Person desk · second org", "credentialId": client},
                  headers=w.who["admin"])
    )  # fmt: skip
    second = str((data(second_made) or {}).get("id") or "con_missing")
    signed = [own_sign_in(w, "admin", first, "priya.own"), own_sign_in(w, "admin", second, "priya.second")]

    # 1. One row for the app, its two accounts a count with a primary, named as the sign-in named them.
    row = mine(w, "admin").get(APP) or {}
    check(
        "1 Priya's Person desk is one row with 2 accounts, primary the team's default, named priya.own at sign-in",
        [s[0] for s in signed] == [200, 200]
        and (row.get("accountCount"), row.get("primaryAccountId"), row.get("account")) == (2, first, "priya.own")
        and row.get("appState") == "connected"
        and row.get("inChat") is True,
        {"signed": signed, "row": row},
    )

    # 2. What it can do, from the tools switched on for the team.
    check(
        "2 the row says what it can do from its switched-on tools, each with its access",
        row.get("canDo") == "Reads: Read a record"
        and [(t.get("title"), t.get("access"), t.get("reviewed")) for t in row.get("tools") or []]
        == [("Read a record", "read", False)],
        {"canDo": row.get("canDo"), "tools": row.get("tools")},
    )

    # 3. Two accounts fit and none is her default: the call asks which, naming both; once she saves one it runs as it,
    # and that call counts on her row while a run acting for nobody does not.
    asked = w.call("person_get_record", args={"id": "rec-1"}, acting_for=PRIYA)
    asked_error = (asked.json() if asked.headers.get("content-type", "").startswith("application/json") else {}).get(
        "error"
    ) or {}
    named = {a.get("account") for a in (asked_error.get("details") or {}).get("accounts") or []}
    saved = w.kept(w.gw.put(f"/v1/apps/{APP}/accounts/{second}/default", headers=w.who["admin"]))
    ran = w.call("person_get_record", args={"id": "rec-1"}, acting_for=PRIYA)
    team_run = w.call("person_get_record", args={"id": "rec-2"})
    row = mine(w, "admin").get(APP) or {}
    used = row.get("used") or {}
    check(
        "3 with two accounts and no default the call asks which; a saved default runs and counts, a run for nobody not",
        asked.status_code == 403
        and asked_error.get("code") == "ACCOUNT_CHOICE_NEEDED"
        and named == {"priya.own", "priya.second"}
        and saved.status_code == 200
        and ran.status_code == 200
        and used.get("callsThisWeek") == 1
        and row.get("primaryAccountId") == second,
        {
            "asked": (asked.status_code, asked_error.get("code"), named),
            "ran": ran.status_code,
            "team": team_run.status_code,
            "used": used,
        },
    )

    # 4. An app the team has off is listed off, and the person who may turn it on is told so.
    sam = mine(w, "security").get(APP) or {}
    check(
        "4 in Security, where Person desk is off, Sam's row says Security needs an auth config, with no accounts, and may be turned on by him",
        sam.get("appState") == "needs_auth_config" and sam.get("accounts") == [] and sam.get("mayManage") is True,
        sam,
    )

    # 5. A call for Sam on that app is refused with the app and team named.
    refused = w.call(
        "person_get_record", team="team_security", args={"id": "rec-1"}, acting_for="s.adeyemi@harborpine.example"
    )
    error = (refused.json() if refused.headers.get("content-type", "").startswith("application/json") else {}).get(
        "error"
    ) or {}
    details = error.get("details") or {}
    check(
        "5 a call on an app off for the team answers 403 APP_OFF_FOR_TEAM naming Person desk and Security",
        refused.status_code == 403
        and error.get("code") == "APP_OFF_FOR_TEAM"
        and (details.get("app"), details.get("appId"), details.get("teamId")) == ("Person desk", APP, "team_security"),
        (refused.status_code, error),
    )

    # 6. The SDK reads the same rows.
    ops = signed_sdk("admin")
    sdk_rows = {str(c["appId"]): c for c in ops.me.connectors.list()}
    check(
        "6 me.connectors.list answers the same one row per app",
        (sdk_rows.get(APP) or {}).get("accountCount") == 2 and len([k for k in sdk_rows if k == APP]) == 1,
        sdk_rows.get(APP),
    )

    # 7. The CLI lists them and disconnects the primary account; the row then names the other.
    code, listed = ops_cli("admin", "connectors", "list")
    end, _ = ops_cli("admin", "connectors", "disconnect", "Person desk")
    after = mine(w, "admin").get(APP) or {}
    check(
        "7 ops connectors list prints the row, and disconnect ends the default sign-in so the other org is primary",
        code == 0
        and isinstance(listed, list)
        and any(r.get("appId") == APP for r in listed)
        and end == 0
        and (after.get("accountCount"), after.get("primaryAccountId")) == (1, first),
        {"list": (code, listed if isinstance(listed, str) else len(listed)), "disconnect": end, "after": after},
    )

finish()
