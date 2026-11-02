"""uc-607, sdk layer: docs/usecases/console/connect-apps.md, story S11 (step 24), group A of an earlier change.

The api layer's stack (docs/usecases/lib/apps_walk.py); the team account of the header-key desk is turned on and
tested through the API, then a developer signed in through the Python SDK in sdk/python lists and reads apps. The SDK's
layer in the screen's words (task K1) calls today's routes. No model call."""

from __future__ import annotations

from apps_layer import attempt
from apps_walk import app_path, apps_stack, signed_sdk
from usecase_harness import check, data, finish

APP = "plugin:test.header-key"

with apps_stack() as w:
    account = w.turn_on("admin", "test.header-key", credentials={"key": w.m["secrets"]["key"]})
    health = w.test("admin", APP, account)
    check("set-up: the team account is turned on and its test passes", health.get("status") == "ok", health)

    # 24. The SDK lists the connected apps and reads one, as the API answers.
    ops = signed_sdk("admin")
    page_api = data(w.gw.get(app_path(APP), headers=w.who["admin"])) or {}
    through_sdk = attempt(ops, "apps", "list", connected=True)
    page_sdk = attempt(ops, "apps", "get", APP)
    check(
        "24 the SDK's apps.list(connected=True) holds the app, every card connected, and apps.get names it",
        through_sdk is not None
        and page_sdk is not None
        and APP in [a["id"] for a in through_sdk]
        # Connected is the team account's state; a card's `status` is the account's display status.
        and all(a.get("state") == "connected" or a.get("kind") == "builtin" for a in through_sdk)
        and page_sdk["card"]["name"] == page_api["card"]["name"],
        {"sdk": through_sdk},
    )

finish()
