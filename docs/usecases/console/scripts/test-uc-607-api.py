"""uc-607, api layer: docs/usecases/console/connect-apps.md, stories S9-S10 (steps 20-23).

The Apps stack of docs/usecases/lib/apps_walk.py: platform-service with the seed's own roles, tools-service with the
nine test plugins installed, and the fake system. The steps call the Apps API
(`GET /v1/apps`, `GET /v1/apps/{id}`, `PUT /v1/apps/{id}/team`, each account under `/v1/apps/{id}/accounts/{account}`);
a check whose behaviour is not built names the task it waits on. No model call."""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlsplit

from apps_walk import account_path, app_path, apps_stack, target
from usecase_harness import check, data, finish, until

APP = "plugin:test.header-key"


def ids(rows: object) -> list[str]:
    return [str(r["id"]) for r in rows] if isinstance(rows, list) else []


# A person's sign-in returns to the console, so its address is set (step 29).
with apps_stack({"OPS_CONSOLE_URL": "https://console.acme.test"}) as w:
    # 20. One list of apps: the plugins and the apps a person added. A built-in app has its own menu.
    listed = w.kept(w.gw.get("/v1/apps", headers=w.who["admin"]))
    kinds = [r.get("kind") for r in data(listed) or []] if listed.status_code == 200 else []
    check(
        "20 GET /v1/apps lists the team's apps in one call, the test plugins among them and no built-in app",
        listed.status_code == 200 and APP in ids(data(listed)) and "builtin" not in kinds,
        (listed.status_code, kinds),
    )

    # 21. A key saved at turn-on is not a sign-in: the app reads Connected only once its test has passed.
    def status() -> str | None:
        r = w.kept(w.gw.get("/v1/apps", headers=w.who["admin"]))
        # The card's state says Connected; its status is the account record's own word.
        return next((c.get("state") for c in data(r) or [] if c.get("id") == APP), None)

    account = w.turn_on("admin", "test.header-key", credentials={"key": w.m["secrets"]["key"]})
    before = status()
    health = w.test("admin", APP, account)
    after = status()
    check(
        "21 the app turned on with a key is not connected before its test passes, and connected after",
        account != "con_missing" and before != "connected" and health.get("status") == "ok" and after == "connected",
        (target("S1 and D2"), {"before": before, "health": health, "after": after}),
    )

    # 22. A viewer sees the apps but may not turn one on.
    seen = w.kept(w.gw.get(app_path(APP), headers=w.who["viewer"]))
    refused = w.kept(w.gw.put("/v1/apps/plugin:test.query-key/team", json={"enabled": True}, headers=w.who["viewer"]))
    check(
        "22 the viewer reads the app (200) and is refused turning one on (403)",
        seen.status_code == 200 and refused.status_code == 403,
        {"read": seen.status_code, "turn on": (refused.status_code, refused.text[:200])},
    )

    # 23. The app's page reads Connected · team account.
    page = data(w.kept(w.gw.get(app_path(APP), headers=w.who["admin"]))) or {}
    accounts = [a for a in page.get("accounts") or [] if a.get("kind") == "team"]
    first = accounts[0] if accounts else {}
    check(
        "23 the app's page lists the team account first, as the default, in state connected",
        first.get("id") == account and first.get("default") is True and first.get("state") == "connected",
        (target("D2"), accounts),
    )

    # 28. A custom tool's own connection holds its address and is reached from the tool, not listed in Apps.
    tool = {
        "name": "uc607_read_rate", "description": "Reads a rate.", "access": "read", "method": "GET",
        "url": "https://rates.uc607.test/v1/rates/{currency}",
    }  # fmt: skip
    body = {"name": "uc607-rates", "displayName": "uc607 rates", "system": "uc607 rates", "http": tool}
    made = w.kept(w.gw.post("/v1/tool-modules", json=body, headers=w.who["admin"]))
    own = str(((data(made) or {}).get("connection") or {}).get("id") or "") if made.status_code == 201 else ""
    after = w.kept(w.gw.get("/v1/apps", headers=w.who["admin"]))
    shown = [(r.get("id"), r.get("kind")) for r in data(after) or []]
    pages = [w.kept(w.gw.get(app_path(a), headers=w.who["admin"])).status_code for a in (own, "builtin:files")]
    check(
        "28 the tool's own connection and the built-in apps are not listed, and both pages still answer",
        bool(own)
        and own not in ids(data(after))
        and not [k for _, k in shown if k in ("builtin", "module")]
        and pages == [200, 200],
        {"made": made.status_code, "own": own, "shown": shown, "pages": pages},
    )

    # 29. An app where each person signs in with their own account: with no team account, James signs in with his own
    # and his call runs as him, through the app's own address.
    person_client = w.credential("admin", "test.person", "multi-app", w.m["clients"]["multi-app"])
    person_app = w.turn_on("admin", "test.person", signIn="person", credentialId=person_client)
    signed = w.sign_in("builder", "plugin:test.person", person_app, "james.own")
    ran = w.call("person_get_record", args={"id": "r-1"}, acting_for="j.richardson@harborpine.example")
    answer = ((data(ran) or {}).get("output") or {}) if ran.status_code == 200 else {}
    check(
        "29 on an app where each person signs in, a person's own sign-in runs a tool before any team account exists",
        person_app != "con_missing" and signed == 200 and answer.get("as") == "james.own",
        {"account": person_app, "sign-in": signed, "call": ran.text[:300]},
    )

    # 30. Signing in is what connects an account; its test then runs on its own, and the outcome is kept on the row.
    def own_row(role: str) -> dict[str, Any]:
        page = data(w.kept(w.gw.get(app_path("plugin:test.person"), headers=w.who[role]))) or {}
        # A person's own sign-in is a row of its own; on an account each person signs in to, the account's row is.
        rows = sorted(page.get("accounts") or [], key=lambda a: a.get("kind") != "person")
        return next((a for a in rows if a.get("mine")), {})

    james_test = until(lambda: (own_row("builder").get("test") or {}).get("status"), timeout=20)
    check(
        "30 a person's own sign-in is tested right after it, as that person, and the row keeps the outcome",
        james_test == "ok" and bool((own_row("builder").get("test") or {}).get("at")),
        own_row("builder"),
    )

    # 31. A sign-in whose test fails still connects; the row warns with the test's reason. The system is down after the
    # sign-in, so the test after it gets a 503.
    w.m["fake"].down = True
    maya_signed = w.sign_in("approver", "plugin:test.person", person_app, "maya.own")
    maya_test = until(lambda: (own_row("approver").get("test") or {}).get("status") == "failed", timeout=30)
    maya = own_row("approver")
    check(
        "31 a sign-in whose test fails is still connected, and its row says the test failed and why",
        maya_signed == 200 and bool(maya_test) and bool((maya.get("test") or {}).get("message")),
        {"sign-in": maya_signed, "row": maya},
    )
    w.m["fake"].down = False

    # 32. The account's Settings read what is saved on it; the secret ones only say whether they are set.
    shown = data(w.kept(w.gw.get(account_path("plugin:test.person", person_app), headers=w.who["admin"]))) or {}
    check(
        "32 an app's account shows its saved settings, as a call reads them",
        (shown.get("pluginSettings") or {}).get("base_url") == "https://api.multi.test"
        and shown.get("pluginSecrets") == {},
        {k: shown.get(k) for k in ("pluginSettings", "pluginSecrets")},
    )

    # 33. A new client id on the credential the person desk signs in with marks its accounts to sign in again and says
    # how many; James's own sign-in on it then reads refused.
    edited = w.kept(
        w.gw.patch(f"/v1/app-credentials/{person_client}", json={"clientId": "multi-app-2"}, headers=w.who["admin"])
    )
    again = (data(edited) or {}).get("signInAgain") if edited.status_code == 200 else None

    def james() -> dict[str, Any]:
        page = data(w.kept(w.gw.get(app_path("plugin:test.person"), headers=w.who["builder"]))) or {}
        rows = sorted(page.get("accounts") or [], key=lambda a: a.get("kind") != "person")
        return next((a for a in rows if a.get("mine")), {})

    check(
        "33 editing a credential's client id marks the accounts signing in with it to sign in again, and says how many",
        again == 1 and james().get("state") == "refused",
        {"edit": edited.text[:300], "james": james()},
    )

    # 34. A refused sign-in: the system hands back access_denied. The answer is one sentence naming who acts, and the
    # account reads refused with that sentence.
    at = account_path("plugin:test.person", person_app)
    started = w.kept(w.gw.post(f"{at}/sign-in", json={"account": "team"}, headers=w.who["admin"]))
    state = parse_qs(urlsplit(str((data(started) or {}).get("authorizeUrl") or "")).query).get("state", [""])[0]
    refusal = {"state": state, "error": "access_denied", "errorDescription": "end-user denied authorization"}
    refused = w.kept(w.gw.post("/v1/sign-ins/complete", json=refusal, headers=w.who["admin"]))
    said = (refused.json().get("error") or {}) if refused.status_code == 422 else {}
    page = data(w.kept(w.gw.get(app_path("plugin:test.person"), headers=w.who["admin"]))) or {}
    row = next((a for a in page.get("accounts") or [] if a.get("kind") == "team" and a.get("id") == person_app), {})
    check(
        "34 a refused sign-in answers one plain sentence naming who acts, and the account reads refused",
        said.get("code") == "sign_in_refused"
        and (said.get("details") or {}).get("who") == "person"
        and said.get("message") == "Person desk access was not given. Connect again to retry."
        and row.get("state") == "refused"
        and row.get("stateReason") == said.get("message"),
        {"answer": refused.text[:300], "row": row},
    )

    # 35. A sign-in place outside the plugin's choices is refused before any sign-in, in plain words.
    outside = {"enabled": True, "signIn": "person", "settings": {"login_url": "https://login.evil.example/salesforce"}}
    place = w.kept(w.gw.put("/v1/apps/plugin:test.person/team", json=outside, headers=w.who["admin"]))
    error = (place.json().get("error") or {}) if place.status_code == 400 else {}
    check(
        "35 a sign-in place outside the plugin's choices is refused with a plain 400 before any sign-in",
        error.get("code") == "setting_not_offered" and "login.multi.test" in str(error.get("message")),
        place.text[:300],
    )

finish()
