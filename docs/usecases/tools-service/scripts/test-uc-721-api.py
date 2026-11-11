"""uc-721, api layer: docs/usecases/tools-service/a-connected-app-writes-at-once.md, stories S1-S3 (steps 1-6).
The Apps stack (docs/usecases/lib/apps_walk.py) with its header-key desk; each run's call is made as agents-service
makes it. No model call."""

from __future__ import annotations

from typing import Any

from apps_walk import app_path, apps_stack
from usecase_harness import check, data, finish, service_headers

APP = "plugin:test.header-key"
POLICY = "/v1/policies/appsChangeWithoutAsking"

with apps_stack() as w:
    # 1. Turned on: every tool added, the write included.
    w.turn_on("admin", "test.header-key", credentials={"key": w.m["secrets"]["key"]})
    page = data(w.kept(w.gw.get(app_path(APP), headers=w.who["admin"]))) or {}
    tools = {t["name"]: t for t in page.get("tools") or []}
    check(
        "1 every tool of the newly added app is added, Close a record included",
        bool(tools) and all(t.get("added") for t in tools.values()) and "header_key_close_record" in tools,
        tools,
    )

    def grantable() -> dict[str, dict[str, Any]]:
        headers = service_headers("tools", tenant=w.tenant, service="agents", team="team_ops", scopes=["tools:view"])
        rows = data(w.kept(w.gw.get("/v1/grantable-operations", headers=headers))) or []
        return {str(o["name"]): o for o in rows}

    # 2. The write asks first; the read does not.
    ops = grantable()
    close, read = ops.get("header_key_close_record") or {}, ops.get("header_key_get_record") or {}
    check(
        "2 Close a record asks first and Read a record does not",
        close.get("asksFirst") is True and read.get("asksFirst") is False,
        (close, read),
    )

    # 3-4. Only a team admin turns it off.
    builder = w.kept(w.api.put(POLICY, json={"value": [APP]}, headers=w.who["builder"]))
    check("3 a builder cannot turn Ask before changes off (403)", builder.status_code == 403, builder.text[:200])
    admin = w.kept(w.api.put(POLICY, json={"value": [APP]}, headers=w.who["admin"]))
    after = grantable().get("header_key_close_record") or {}
    check(
        "4 the team admin turns it off and the write asks no more",
        admin.status_code == 200 and after.get("asksFirst") is False,
        (admin.text[:200], after),
    )

    # 5. A live write runs with no approval of its own.
    ran = w.call("header_key_close_record", args={"id": "rec-1042"})
    check(
        "5 a live run's write runs (200) with no approval",
        ran.status_code == 200 and (data(ran) or {}).get("ok") is True,
        ran.text[:300],
    )

    # 6. A tool turned off says why and where to turn it on.
    removed = w.kept(w.gw.delete(f"{app_path(APP)}/tools/header_key_close_record", headers=w.who["admin"]))
    off = w.call("header_key_close_record", args={"id": "rec-1042"})
    # Refused before any request leaves, as the run's outcome or the route's error, naming what is off and where.
    body = off.json() or {}
    error = body.get("error") or (((body.get("data") or {}).get("output") or {}).get("error")) or {}
    details = error.get("details") or {}
    check(
        "6 a run calling the turned-off tool is refused with the app, the tool's title and where to turn it on",
        error.get("code") == "TOOL_NOT_ADDED"
        and details.get("appId") == APP
        and details.get("toolTitle") == "Close a record",
        (removed.status_code, off.status_code, off.text[:400]),
    )

finish()
