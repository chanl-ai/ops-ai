"""uc-626, api layer: docs/usecases/tools-service/apps-screens-for-each-role.md, story S1 (step 1). What the Apps API
says when it refuses a person reads in plain words: it names the thing and who may act, never an area or action
name, a team id or an internal word. The Apps stack (docs/usecases/lib/apps_walk.py). No model call."""

from __future__ import annotations

import re
from typing import Any

from apps_walk import apps_stack
from usecase_harness import check, finish

# Words a person should never read: the grid's cell names, team ids, and the service's own nouns.
INTERNAL = re.compile(
    r"\b(connections?|plugins?|modules?|binding|egress|gateway|oauth|team_ops|team_security)\b|\.manage|\.edit|\ba agent\b",
    re.IGNORECASE,
)

with apps_stack() as w:
    viewer = w.who["viewer"]
    asks: dict[str, Any] = {
        "list auth configs": w.gw.get("/v1/app-credentials", headers=viewer),
        "add a custom app": w.gw.post("/v1/apps", json={"name": "Desk", "authKind": "api_key"}, headers=viewer),
        "turn an app on": w.gw.put("/v1/apps/plugin:test.client/team", json={"enabled": True}, headers=viewer),
        "add a secret": w.gw.post("/v1/secrets", json={"name": "DESK_KEY", "value": "desk-key-1234"}, headers=viewer),
    }
    said = {what: (r.status_code, (r.json().get("error") or {}).get("message", "")) for what, r in asks.items()}
    leaks = {what: m for what, (_, m) in said.items() if INTERNAL.search(m)}
    check(
        "1 every refusal a viewer meets on the Apps API is a plain sentence naming the thing and who may act",
        all(status == 403 and message for status, message in said.values()) and not leaks,
        {"said": said, "leaks": leaks},
    )
finish()
