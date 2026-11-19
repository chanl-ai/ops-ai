"""uc-721, sdk layer: docs/usecases/tools-service/a-connected-app-writes-at-once.md, story S4 (step 7).
The api layer's stack; the team admin turns the header-key desk on, and James reads its page through the Python SDK's
generated client (`ops.raw.tools`) over `GET /v1/apps/{app}`. No model call."""

from __future__ import annotations

from typing import Any

from apps_walk import app_path, apps_stack, signed_sdk
from usecase_harness import check, data, finish

APP = "plugin:test.header-key"

with apps_stack() as w:
    w.turn_on("admin", "test.header-key", credentials={"key": w.m["secrets"]["key"]})
    ops: Any = signed_sdk("builder")
    page = ops.raw.tools.apps_get_app(APP)
    through_sdk = {str(t["name"]): bool(t.get("added")) for t in page.get("tools") or []}
    through_api = {
        t["name"]: bool(t.get("added"))
        for t in (data(w.gw.get(app_path(APP), headers=w.who["builder"])) or {}).get("tools") or []
    }
    check(
        "7 the SDK's app page lists the desk's tools, all added, as the API does",
        bool(through_sdk) and through_sdk == through_api and all(through_sdk.values()),
        {"sdk": through_sdk, "api": through_api},
    )

finish()
