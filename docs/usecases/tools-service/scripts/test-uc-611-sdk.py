"""uc-611, sdk layer: docs/usecases/tools-service/a-developer-builds-a-rest-tool.md, story S8 (step 14).
The Apps stack (docs/usecases/lib/apps_walk.py) and its fake system's Bearer endpoint: a builder signed in
through the Python SDK adds a custom REST app holding the base address and the token, adds a tool addressed by its path
alone, and runs it Real. Apps and tools come from the SDK's layer in the screen's words (K1),
over today's connection routes and the tool page's run route (P1). No model call."""

from __future__ import annotations

from apps_layer import attempt
from apps_walk import apps_stack, signed_sdk, target
from fake_multi_auth import digest
from usecase_harness import check, finish

with apps_stack() as w:
    ops = signed_sdk("builder")
    token = w.m["secrets"]["token"]

    # 14. A custom REST app holds the base address and the token; a tool addressed by its path runs Real with both.
    app = attempt(
        ops, "apps", "add_custom", "rest", "Records desk", auth_kind="bearer", base_address=w.m["api_base"],
        secrets={"token": token},
    )  # fmt: skip
    app_id = str((app or {}).get("id") or "")
    tool = None
    try:
        tool = ops.raw.tools.tool_modules_create_module(
            {
                "name": "records-desk",
                "displayName": "Records desk",
                "type": "http",
                "connectionId": app_id,
                "http": {
                    "name": "read_record",
                    "description": "Reads a record.",
                    "access": "read",
                    "method": "GET",
                    "url": "/bearer/records/{id}",
                },
            }
        )
    except Exception as e:  # a path-only address is refused until S4; the check below reports it
        print(f"note: the tool was not made: {str(e)[:160]}")
    ran = attempt(ops, "tools", "run", app_id, "read_record", {"id": "rec-1042"}, real=True) if tool else None
    seen = next((c for c in reversed(w.m["fake"].state()["calls"]) if c["method"] == "bearer"), {})
    check(
        "14 through the SDK a custom REST app holds the base address and token, and a tool addressed by its path runs "
        "Real with both",
        ran is not None
        and "rec-1042" in str(ran.get("output"))
        and seen.get("credential") == digest(token)
        and token not in str(ran),
        (target("P1, S4 and K1"), {"app": app, "ran": ran, "seen": seen}),
    )

finish()
