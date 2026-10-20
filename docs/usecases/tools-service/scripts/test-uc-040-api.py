"""uc-040 Security decides a tool module review, api layer: docs/usecases/tools-service/security-decides-a-module-review.md.
platform-service issues the people's tokens; tools-service and agents-service verify them (OPS_AUTH_MODE=platform). The
review is a publish request decided in agents-service's Reviews, as Human Tasks decides it (c-163)."""

from __future__ import annotations

import time
from typing import Any

import httpx

from usecase_harness import (
    AGENTS_PORT,
    PLATFORM_INTERNAL_PORT,
    PLATFORM_PORT,
    agents,
    check,
    data,
    finish,
    platform,
    tools,
)

RUN = int(time.time())
HOST = f"statements-{RUN}.bank.example"
PASSWORD = "northfield-demo"


def signed_in(pub: httpx.Client, email: str, team: str) -> dict[str, str]:
    token = data(pub.post("/v1/auth/sign-in", json={"email": email, "password": PASSWORD}))["token"]
    return {"Authorization": f"Bearer {token}", "X-Team-Id": team}


def reviewed_module(gw: httpx.Client, james: dict[str, str], name: str) -> tuple[str, str]:
    made = data(
        gw.post("/v1/tool-modules/blank", json={"displayName": name, "name": name, "type": "http"}, headers=james)
    )
    op = {
        "name": f"{name.replace('-', '_')}_get",
        "description": "",
        "access": "read",
        "method": "GET",
        "url": f"https://{HOST}/v1/x",
    }
    gw.post(f"/v1/tool-modules/{made['id']}/operations", json=op, headers=james)
    reviewed = data(gw.post(f"/v1/tool-modules/{made['id']}/reviews", json={"note": "uc-040"}, headers=james))
    return made["id"], next(v["reviewId"] for v in reviewed["versions"] if v["status"] == "in_review")


def waiting(gw: httpx.Client, who: dict[str, str]) -> list[dict[str, Any]]:
    return data(gw.get("/v1/tool-modules", params={"view": "security_review", "pageSize": 100}, headers=who))["data"]


settings = {
    "OPS_AUTH_MODE": "platform",
    "OPS_PLATFORM_URL": f"http://127.0.0.1:{PLATFORM_PORT}",
    "OPS_PLATFORM_INTERNAL_PORT": str(PLATFORM_INTERNAL_PORT),
}
with (
    platform() as (pub, _internal),
    agents(env=settings) as api,
    tools(settings={**settings, "OPS_AGENTS_URL": f"http://127.0.0.1:{AGENTS_PORT}"}) as gw,
):
    james = signed_in(pub, "j.richardson@northfieldbank.com", "team_ops")
    maya = signed_in(pub, "m.okafor@northfieldbank.com", "team_ops")
    nadia = signed_in(pub, "n.petrov@northfieldbank.com", "team_security")
    sam = signed_in(pub, "s.adeyemi@northfieldbank.com", "team_security")
    allowed = gw.post("/v1/egress/hosts", json={"value": HOST, "note": "uc-040"}, headers=sam)
    check("Security's admin allows the module's host for egress", allowed.status_code in (200, 201), allowed.text[:200])
    mid, rid = reviewed_module(gw, james, f"uc040-statements-{RUN}")
    row = next((m for m in waiting(gw, nadia) if m["id"] == mid), None)
    check(
        "Security's view lists the module with its pending review",
        row is not None and row["pendingReview"]["requestedBy"] == "James Richardson",
        row,
    )

    decide = f"/v1/publish-requests/{rid}/decision"
    own = api.post(decide, json={"decision": "approved"}, headers=james)
    check("the requester cannot decide their own review (403)", own.status_code == 403, own.text[:200])
    elsewhere = api.post(decide, json={"decision": "approved"}, headers=maya)
    check(
        "an approver on another team cannot clear it (403 naming team_security)",
        elsewhere.status_code == 403 and "team_security" in elsewhere.text,
        elsewhere.text[:200],
    )
    bare = api.post(decide, json={"decision": "returned"}, headers=nadia)
    check("returning it needs a reason (400)", bare.status_code == 400, bare.text[:200])
    approved = api.post(decide, json={"decision": "approved"}, headers=nadia)
    module = data(gw.get(f"/v1/tool-modules/{mid}", headers=nadia))
    check(
        "Security's approver approves in Reviews and the module is published",
        approved.status_code == 200 and module["status"] == "published",
        approved.text[:200],
    )
    check("a decided review leaves Security's view", all(m["id"] != mid for m in waiting(gw, nadia)))

    other, other_rid = reviewed_module(gw, james, f"uc040-holds-{RUN}")
    why = ["place_hold must need an approval token"]
    changed = api.post(
        f"/v1/publish-requests/{other_rid}/decision", json={"decision": "returned", "reason": why[0]}, headers=nadia
    )
    detail = data(gw.get(f"/v1/tool-modules/{other}", headers=nadia))
    finding = next((v.get("finding") for v in detail["versions"] if v.get("reviewId") == other_rid), None)
    check(
        "returning it sends a new module back to draft with the reason",
        changed.status_code == 200 and detail["status"] == "draft" and finding == why[0],
        changed.text[:200],
    )

finish()
