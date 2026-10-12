"""uc-040 Security decides a tool module review, api layer: docs/usecases/tools-service/security-decides-a-module-review.md.
platform-service issues the people's tokens; tools-service verifies them (OPS_AUTH_MODE=platform)."""

from __future__ import annotations

import time
from typing import Any

import httpx

from usecase_harness import PLATFORM_INTERNAL_PORT, PLATFORM_PORT, check, data, finish, platform, tools

RUN = int(time.time())
HOST = f"statements-{RUN}.bank.example"
PASSWORD = "northfield-demo"


def signed_in(pub: httpx.Client, email: str, team: str) -> dict[str, str]:
    token = data(pub.post("/v1/auth/sign-in", json={"email": email, "password": PASSWORD}))["token"]
    return {"Authorization": f"Bearer {token}", "X-Team-Id": team}


def reviewed_module(gw: httpx.Client, james: dict[str, str], name: str) -> tuple[str, str]:
    made = data(gw.post("/v1/tool-modules/blank", json={"displayName": name, "name": name, "type": "http"}, headers=james))
    op = {"name": f"{name.replace('-', '_')}_get", "description": "", "access": "read", "method": "GET", "url": f"https://{HOST}/v1/x"}
    gw.post(f"/v1/tool-modules/{made['id']}/operations", json=op, headers=james)
    reviewed = data(gw.post(f"/v1/tool-modules/{made['id']}/reviews", json={"note": "uc-040"}, headers=james))
    return made["id"], next(r["id"] for r in reviewed["reviews"] if r["decision"] == "pending")


def waiting(gw: httpx.Client, who: dict[str, str]) -> list[dict[str, Any]]:
    return data(gw.get("/v1/tool-modules", params={"view": "security_review", "pageSize": 100}, headers=who))["data"]


settings = {
    "OPS_AUTH_MODE": "platform",
    "OPS_PLATFORM_URL": f"http://127.0.0.1:{PLATFORM_PORT}",
    "OPS_PLATFORM_INTERNAL_PORT": str(PLATFORM_INTERNAL_PORT),
}
with platform() as (pub, _internal), tools(settings=settings) as gw:
    james = signed_in(pub, "j.richardson@northfieldbank.com", "team_ops")
    maya = signed_in(pub, "m.okafor@northfieldbank.com", "team_ops")
    nadia = signed_in(pub, "n.petrov@northfieldbank.com", "team_security")
    gw.post("/v1/egress/hosts", json={"value": HOST, "note": "uc-040"}, headers=james)
    mid, rid = reviewed_module(gw, james, f"uc040-statements-{RUN}")
    row = next((m for m in waiting(gw, nadia) if m["id"] == mid), None)
    check("Security's view lists the module with its pending review", row is not None and row["pendingReview"]["requestedBy"] == "James Richardson", row)

    decide = f"/v1/tool-modules/{mid}/reviews/{rid}/decide"
    own = gw.post(decide, json={"decision": "approved"}, headers=james)
    check("the requester cannot decide their own review (403)", own.status_code == 403, own.text[:200])
    elsewhere = gw.post(decide, json={"decision": "approved"}, headers=maya)
    check(
        "an approver on another team cannot clear it (403 naming the Security team)",
        elsewhere.status_code == 403 and "Security team" in elsewhere.text,
        elsewhere.text[:200],
    )
    bare = gw.post(decide, json={"decision": "changes_requested"}, headers=nadia)
    check("requesting changes needs a reason (400)", bare.status_code == 400, bare.text[:200])
    approved = gw.post(decide, json={"decision": "approved"}, headers=nadia)
    check("Security's approver approves and the module is published", approved.status_code == 200 and data(approved)["status"] == "published", approved.text[:200])
    check("a decided review leaves Security's view", all(m["id"] != mid for m in waiting(gw, nadia)))

    other, other_rid = reviewed_module(gw, james, f"uc040-holds-{RUN}")
    why = ["place_hold must need an approval token"]
    changed = gw.post(f"/v1/tool-modules/{other}/reviews/{other_rid}/decide", json={"decision": "changes_requested", "findings": why}, headers=nadia)
    detail = data(changed) or {}
    findings = next((r["findings"] for r in detail.get("reviews", []) if r["id"] == other_rid), None)
    check("a change request sends a new module back to draft with the reason", changed.status_code == 200 and detail.get("status") == "draft" and findings == why, changed.text[:200])

finish()
