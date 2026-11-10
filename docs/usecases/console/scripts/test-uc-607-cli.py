"""uc-607, cli layer: docs/usecases/console/connect-apps.md, story S12 (steps 25-26).

The api layer's stack (docs/usecases/lib/apps_walk.py). A team admin and a viewer run `opsai apps` from the repo,
signed in as their dev role the way `make api` signs in (task L1: the opsai command over the SDK). No model call."""

from __future__ import annotations

from apps_walk import apps_stack, ops_cli, target
from usecase_harness import check, finish

APP = "plugin:test.header-key"

with apps_stack() as w:
    account = w.turn_on("admin", "test.header-key", credentials={"key": w.m["secrets"]["key"]})
    health = w.test("admin", APP, account)
    check("set-up: the team account is turned on and its test passes", health.get("status") == "ok", health)

    # 25. opsai apps list and show, as the team admin.
    code, listed = ops_cli("admin", "apps", "list", "--connected")
    shown_code, shown = ops_cli("admin", "apps", "show", APP)
    check(
        "25 `opsai apps list --connected` lists the app and `opsai apps show` names it, both exit 0",
        code == 0
        and isinstance(listed, list)
        and APP in [a.get("id") for a in listed]
        and shown_code == 0
        and isinstance(shown, dict)
        and shown.get("card", {}).get("name") == "Header key desk",
        (target("L1"), {"list": (code, listed), "show": (shown_code, shown)}),
    )

    # 26. A viewer may not turn an app on from the command line either.
    code, out = ops_cli("viewer", "apps", "connect", "plugin:test.query-key")
    check(
        "26 a viewer's `opsai apps connect` exits non-zero naming the 403",
        code not in (0, 2) and "403" in str(out),
        (target("L1"), code, out),
    )

finish()
