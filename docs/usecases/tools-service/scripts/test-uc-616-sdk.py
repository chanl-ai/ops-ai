"""uc-616, sdk layer: docs/usecases/tools-service/usage-shows-only-this-team-s.md, story S4 (step 5), group G of
an earlier change. The api layer's stack; a run in team_ops reads a record, and the team admin reads Usage through the Python SDK
layer in the screen's words (K1) over `GET /v1/executions`. No model call."""

from __future__ import annotations

from apps_layer import attempt
from apps_walk import apps_stack, signed_sdk, target
from usecase_harness import check, data, finish

with apps_stack() as w:
    w.turn_on("admin", "test.header-key", credentials={"key": w.m["secrets"]["key"]})
    ran = w.call("header_key_get_record", args={"id": "rec-1042"})
    check("set-up: a run in team_ops reads a record (200)", ran.status_code == 200, ran.text[:200])

    # 5. The SDK's Usage is the API's.
    ops = signed_sdk("admin")
    through_sdk = attempt(ops, "usage", "list")
    through_api = (data(w.gw.get("/v1/executions", headers=w.who["admin"])) or {}).get("data")
    check(
        "5 the SDK's usage.list gives the API's rows, holding the run's call",
        through_sdk is not None
        and through_sdk == through_api
        and str((data(ran) or {}).get("callId")) in str(through_sdk),
        (target("K1"), {"sdk": through_sdk, "api": through_api}),
    )

finish()
