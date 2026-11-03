"""uc-615, api layer: docs/usecases/tools-service/a-team-admin-sets-its-own.md, stories S1-S4 (steps 1-5).
The Apps stack (docs/usecases/lib/apps_walk.py); the fake's sign-in server knows the client `multi-app`.
A check whose behaviour is not built names the task it waits on. No model call."""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlsplit

from apps_walk import account_path, apps_stack, target
from usecase_harness import check, data, finish

APP = "plugin:test.person"


def team_account(w: Any, account: str) -> dict[str, Any]:
    """The app's team account as its detail answers it."""
    return dict(data(w.kept(w.gw.get(account_path(APP, account), headers=w.who["admin"]))) or {})


with apps_stack(ops_ai_apps={"test.person": "multi-zoom"}) as w:
    secret = w.m["clients"]["multi-app"]
    admin, builder = w.who["admin"], w.who["builder"]

    # 1. Turned on with no app of its own, the app signs in with Ops AI's app.
    account = w.turn_on("admin", "test.person", signIn="team")
    first = team_account(w, account)
    check(
        "1 the app turned on with no credential of the team's signs in with Ops AI's app",
        account != "con_missing" and first.get("platformApp") == "test.person",
        first,
    )

    # 2. The team's own client id and secret, on the account; read back with no secret.
    path = account_path(APP, account)
    own = {"settings": {"clientId": "multi-app"}, "secretValues": {"clientSecret": secret}}
    saved = w.kept(w.gw.patch(path, json={"revision": first.get("revision"), **own}, headers=admin))
    read = team_account(w, account)
    check(
        "2 the team's own app credential is saved: Ops AI's app is no longer used, the client is multi-app, and no "
        "answer carries the secret",
        saved.status_code == 200
        and not read.get("platformApp")
        and (read.get("settings") or {}).get("clientId") == "multi-app"
        and not any(secret in t for t in w.seen),
        (target("P1: the account route takes the team's own client"), saved.status_code, saved.text[:200], read),
    )

    # 3. Test with my account: a sign-in through the team's app, answered back on the same route.
    test = f"{path}/test-credential"
    started = w.kept(w.gw.post(test, json={}, headers=admin))
    url = str((data(started) or {}).get("authorizeUrl") or "") if started.status_code == 200 else ""
    client = parse_qs(urlsplit(url).query).get("client_id", [""])[0]
    back = w.m["sign_in"](url, "harbor.ops") if url else {}
    done = w.kept(w.gw.post(test, json={"state": back.get("state"), "code": back.get("code")}, headers=admin))
    health = (data(done) or {}).get("health") or {}
    check(
        "3 Test with my account signs in through client multi-app and answers ok as harbor.ops",
        client == "multi-app" and health.get("status") == "ok" and health.get("account") == "harbor.ops",
        (target("P1"), {"start": started.text[:200], "done": done.text[:200]}),
    )

    # 4. Only an admin sets an app credential.
    refused = w.kept(
        w.gw.patch(path, json={"revision": team_account(w, account).get("revision"), **own}, headers=builder)
    )
    check("4 the builder is refused setting the app credential (403)", refused.status_code == 403, refused.text[:200])

    # 5. Secrets holds values tools reference; no sign-in shows there.
    made = w.kept(w.gw.post("/v1/secrets", json={"name": "DESK_WEBHOOK", "value": "whk-7d1e40c2"}, headers=admin))
    names = [s.get("name") for s in data(w.kept(w.gw.get("/v1/secrets", headers=admin))) or []]
    check(
        "5 Secrets lists the tool's secret with no value, and nothing for the app's client or a sign-in",
        made.status_code in (200, 201)
        and "DESK_WEBHOOK" in names
        and not any("multi-app" in str(n) or "sign" in str(n).lower() for n in names)
        and not any("whk-7d1e40c2" in t for t in w.seen[-1:]),
        {"made": made.text[:200], "names": names},
    )

finish()
