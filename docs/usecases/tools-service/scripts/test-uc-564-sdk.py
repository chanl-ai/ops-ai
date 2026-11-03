"""uc-564, sdk layer: docs/usecases/tools-service/a-team-turns-on-the-salesforce.md, story S10 (step 43).
The Apps stack (docs/usecases/lib/apps_walk.py) and its fake system: the header-key desk is on for the team
account, and a builder signed in through the Python SDK lists the app's tools and runs one Mock and Real with the
SDK's layer in the screen's words (K1) over the tool page's run route (P1). No model call."""

from __future__ import annotations

from apps_layer import attempt
from apps_walk import apps_stack, signed_sdk, target
from usecase_harness import check, finish

APP = "plugin:test.header-key"
TOOL = "header_key_get_record"

with apps_stack() as w:
    account = w.turn_on("admin", "test.header-key", credentials={"key": w.m["secrets"]["key"]})
    check("set-up: the header-key desk is on with the team's key", account != "con_missing", account)

    # 43. Tools listed and run through the SDK: Mock reaches nothing, Real reads the record.
    ops = signed_sdk("builder")
    listed = attempt(ops, "tools", "list", APP)
    sent = len(w.m["fake"].state()["calls"])
    mocked = attempt(ops, "tools", "run", APP, TOOL, {"id": "rec-1042"}, real=False)
    after_mock = len(w.m["fake"].state()["calls"])
    real = attempt(ops, "tools", "run", APP, TOOL, {"id": "rec-1042"}, real=True)
    check(
        "43 the SDK's tools.list names the app's tools, tools.run Mock reaches nothing and Real reads the record",
        listed is not None
        and TOOL in [t.get("name") for t in listed]
        and mocked is not None
        and mocked.get("mocked") is True
        and after_mock == sent
        and real is not None
        and (real.get("output") or {}).get("record", {}).get("id") == "rec-1042",
        (target("P1 and K1"), {"listed": listed, "mocked": mocked, "real": real}),
    )

finish()
