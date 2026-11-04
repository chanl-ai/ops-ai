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

    # 6. Made through the SDK's credentials.create with no account, then picked with credentials.set: the team account
    # then holds the team's client, with no secret shown.
    ops = signed_sdk("admin")
    made = attempt(ops, "credentials", "create", APP, client_id="multi-app", client_secret=secret) or {}
    saved = attempt(ops, "credentials", "set", APP, made.get("id"))
    held = data(w.gw.get(account_path(APP, account), headers=w.who["admin"])) or {}
    check(
        "6 the SDK's credentials.create makes the team's own client and credentials.set puts the app on it: Ops AI's "
        "app is no longer used, and no answer has the secret",
        saved is not None
        and held.get("credentialId") == made.get("id")
        and (held.get("settings") or {}).get("clientId") == "multi-app"
        and not held.get("platformApp")
        and secret not in str(saved) + str(made),
        (target("K1"), {"made": made, "saved": saved, "account": held}),
    )

finish()
