"""uc-615, sdk layer: docs/usecases/tools-service/a-team-admin-sets-its-own.md, story S5 (step 6), group B of an earlier change.
The api layer's stack; a developer signed in through the Python SDK sets the app credential with the layer in the
screen's words (K1), which calls today's environment route. No model call."""

from __future__ import annotations

from apps_layer import attempt
from apps_walk import apps_stack, signed_sdk, target
from usecase_harness import check, data, finish

APP = "plugin:test.person"

with apps_stack(ops_ai_apps={"test.person": "multi-zoom"}) as w:
    secret = w.m["clients"]["multi-app"]
    account = w.turn_on("admin", "test.person", signIn="team")
    check("set-up: the person desk is on for the team account", account != "con_missing", account)

    # 6. Set through the SDK's credentials.set; the environment then holds the team's client, with no secret shown.
    ops = signed_sdk("admin")
    saved = attempt(ops, "credentials", "set", APP, client_id="multi-app", client_secret=secret)
    detail = data(w.gw.get(f"/v1/connections/{account}", headers=w.who["admin"])) or {}
    env = (detail.get("environments") or {}).get("production") or {}
    check(
        "6 the SDK's credentials.set puts the team's own client on the app, Ops AI's app is no longer used, and the "
        "answer has no secret",
        saved is not None
        and (env.get("settings") or {}).get("clientId") == "multi-app"
        and not env.get("platformApp")
        and secret not in str(saved),
        (target("K1"), {"saved": saved, "env": env}),
    )

finish()
