"""uc-588, sdk layer: docs/usecases/tools-service/plugin-sign-in-methods.md, story S11 (step 34).
The Apps stack (docs/usecases/lib/apps_walk.py); the person-key desk is on for person sign-in, and Maya gives, reads
and removes her own key through the SDK's layer in the screen's words (K1), over today's
/v1/me/accounts routes.
No model call."""

from __future__ import annotations

from apps_layer import attempt
from apps_walk import apps_stack, signed_sdk, target
from usecase_harness import check, data, finish

APP = "plugin:test.person-key"

with apps_stack() as w:
    account = w.turn_on("admin", "test.person-key", signIn="person")
    check("set-up: the person-key desk is on for person sign-in", account != "con_missing", account)

    # 34. Maya's own key through the SDK: given, listed as connected as the API lists it, then removed.
    ops = signed_sdk("approver")
    gave = attempt(ops, "accounts", "set_key", account, w.m["person_keys"]["maya"])
    health = w.test("approver", APP, account)
    through_sdk = attempt(ops, "accounts", "mine")
    through_api = data(w.gw.get("/v1/me/accounts", headers=w.who["approver"]))
    removed = attempt(ops, "accounts", "remove", account)
    after = attempt(ops, "accounts", "mine")
    row = next((r for r in through_sdk or [] if r.get("connectionId") == account), {})
    later = next((r for r in after or [] if r.get("connectionId") == account), {})
    check(
        "34 Maya gives her key through the SDK's accounts.set_key, accounts.mine reads it connected as the API does, "
        "and accounts.remove takes it away",
        gave is not None
        and health.get("status") == "ok"
        and through_sdk == through_api
        and row.get("connected") is True
        and removed is not None
        and not later.get("connected")
        and w.m["person_keys"]["maya"] not in str(through_sdk),
        (target("K1"), {"sdk": through_sdk, "health": health, "after": after}),
    )

finish()
