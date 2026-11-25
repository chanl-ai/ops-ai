"""uc-790, api layer: docs/usecases/tools-service/chat-never-asks-whose-login.md, stories S1, S2 and S4 (steps 1-4).
The Apps stack (docs/usecases/lib/apps_walk.py). No model call."""

from __future__ import annotations

from apps_walk import account_path, app_path, apps_stack
from usecase_harness import check, data, finish

APP = "plugin:test.header-key"
JAMES = "j.richardson@harborpine.example"

with apps_stack() as w:
    # 1. Priya sets the header key desk to Everyone uses the team's login; James's agent reads a record.
    account = w.turn_on("admin", "test.header-key", credentials={"key": w.m["secrets"]["key"]})
    page = data(w.kept(w.gw.get(app_path(APP), headers=w.who["admin"]))) or {}
    login = next((str(a.get("name")) for a in page.get("accounts") or [] if a.get("id") == account), "")
    r = w.call("header_key_get_record", args={"id": "rec-1042"}, acting_for=JAMES)
    answer = data(r) or {}
    signed = answer.get("signedIn") or {}
    check(
        "1 a call James asked for on a team-login app runs at once and says it ran as the team login",
        r.status_code == 200 and answer.get("ok") is True and signed.get("whose") == "team" and signed.get("login") == login,
        (r.status_code, login, signed, str(answer.get("output"))[:200]),
    )

    # 2. The audit row holds both the team login and the person who asked.
    row = data(w.kept(w.gw.get(f"/v1/executions/{answer.get('callId')}", headers=w.who["admin"]))) or {}
    check(
        "2 the call's audit row names the team login it ran as and James as the person who asked",
        row.get("runAs") == {"kind": "team", "login": login, "askedBy": JAMES} and row.get("actingFor") == JAMES,
        {k: row.get(k) for k in ("runAs", "actingFor", "credential", "connectionId")},
    )

    # 3. Each person signs in: James's first call asks him to sign in, once; after his key the next calls ask nothing.
    desk = w.turn_on("admin", "test.person-key", signIn="person")
    first = data(w.call("person_key_get_record", args={"id": "rec-1042"}, acting_for=JAMES)) or {}
    error = (first.get("output") or {}).get("error") or {}
    given = w.kept(
        w.gw.put(
            f"/v1/me/accounts/{desk}/credentials",
            json={"credentials": {"key": w.m["person_keys"]["james"]}},
            headers=w.who["builder"],
        )
    )
    after = [data(w.call("person_key_get_record", args={"id": "rec-1042"}, acting_for=JAMES)) or {} for _ in range(2)]
    check(
        "3 on an each-person app James is asked to sign in once, then his next two calls run as him and ask nothing",
        error.get("code") == "CONNECTION_NOT_LINKED"
        and given.status_code == 200
        and all(a.get("ok") is True and (a.get("signedIn") or {}).get("whose") == "person" for a in after),
        (error.get("code"), given.status_code, [(a.get("ok"), a.get("signedIn")) for a in after]),
    )

    # 4. Who signs in is the admin's setting: a builder cannot change it; Priya can, and it reads back.
    path = account_path(APP, account)
    revision = (data(w.gw.get(path, headers=w.who["admin"])) or {}).get("revision")
    by_james = w.gw.patch(path, json={"revision": revision, "signIn": "team"}, headers=w.who["builder"])
    shown = (data(w.gw.get(path, headers=w.who["admin"])) or {}).get("signIn")
    check(
        "4 a builder is refused changing who signs in (connections.manage) and the app still reads the team's login",
        by_james.status_code == 403 and shown == "team",
        (by_james.status_code, by_james.text[:200], shown),
    )

finish()
