"""uc-615, sdk layer: docs/usecases/tools-service/a-team-admin-sets-its-own.md, story S5 (step 6).
The api layer's stack; a developer signed in through the Python SDK sets the app credential with the layer in the
screen's words (K1), which calls the account route. No model call."""

from __future__ import annotations

from apps_layer import attempt
from apps_walk import account_path, apps_stack, signed_sdk, target
from usecase_harness import check, data, finish

APP = "plugin:test.person"

with apps_stack(ops_ai_apps={"test.person": "multi-zoom"}) as w:
    secret = w.m["clients"]["multi-app"]
    account = w.turn_on("admin", "test.person", signIn="team")
    check("set-up: the person desk is on for the team account", account != "con_missing", account)

    # 6. Set through the SDK's credentials.set, and the team account then holds the team's client, with no secret shown.
    ops = signed_sdk("admin")
    saved = attempt(ops, "credentials", "set", APP, client_id="multi-app", client_secret=secret)
    held = data(w.gw.get(account_path(APP, account), headers=w.who["admin"])) or {}
    check(
        "6 the SDK's credentials.set puts the team's own client on the app, Ops AI's app is no longer used, and the "
        "answer has no secret",
        saved is not None
        and (held.get("settings") or {}).get("clientId") == "multi-app"
        and not held.get("platformApp")
        and secret not in str(saved),
        (target("K1"), {"saved": saved, "account": held}),
    )

finish()
