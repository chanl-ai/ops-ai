"""An app's first address on a host the tenant has not listed, held for a Security admin as an ordinary
publish request: opened by tools-service when a person first sets the address, listed in Human Tasks as an
`egress_host` task with the host, the app and who asked joined in, decided by the Security team, and applied back in
tools-service, which lists the host on approval.

The request's id is the run key tools-service answers with: the person's screen retries once it is approved, and a
refusal's reason is read against it. One request per host is open at a time: a second attempt while it waits returns
the same one, and an attempt after a refusal returns the refusal instead of asking again."""

from __future__ import annotations

from typing import Any

from ops_access import can
from ops_service_kit.errors import ServiceUnavailable
from ops_service_kit.ids import now_iso

from .agent_registry import registry, review_view
from .auth import Principal, caller_of
from .deps import Runtime
from .review_sla import sla_hours
from .team_names import security_team

KIND = "egress_host"


async def open_review(rt: Runtime, me: Principal, host: str, app: str) -> tuple[dict[str, Any], bool]:
    """The request for `host` and whether it is new: the one still waiting, else the latest refusal, else a new one.
    `me` is the person setting the address, from their own credentials; the team is theirs, never the body's."""
    team = me.team_id or ""
    # Setting an app's address is a tool builder's change, as on tools-service's own route.
    can(caller_of(me), "tools", "create", team=team or None, what="an app's address")
    held = await registry(rt).requests(KIND, host)
    latest = held[0] if held else None
    if latest is not None and latest["status"] in ("pending", "rejected"):
        return latest, False
    body = {"host": host, "app": app, "teamId": team, "requestedBy": me.email}
    made = await registry(rt).open_request(
        KIND, host, 1, note=f"{app} calls {host}", by=me.email, body=body, approved=False
    )
    return made, True


async def team(rt: Runtime) -> str | None:
    """The workspace's Security team decides every host, as it keeps the tenant's allow-list."""
    return await security_team(rt)


async def view(rt: Runtime, req: dict[str, Any]) -> dict[str, Any]:
    if req["body"].get("applyPending"):
        req = await _apply(rt, req)
    body = req["body"]
    v = review_view(req, name=body["app"], slug="", sla_hours=await sla_hours(rt))
    v.pop("publish", None)
    policy = {**v["policy"], "id": "gp_egress_host", "name": "New host", "reviewers": "Security"}
    return {
        **v,
        "kind": KIND,
        "title": f"Let {body['app']} call {body['host']}?",
        "workflowId": "",
        "actionTool": "allow_egress_host",
        "policy": policy,
        "reasoning": [f"{body['requestedBy']} set {body['app']}'s address on {body['host']}, which is not listed."],
        "egressHost": {
            "host": body["host"],
            "app": body["app"],
            "requestedBy": body["requestedBy"],
            "teamId": body["teamId"],
            "applyPending": bool(body.get("applyPending")),
        },
    }


async def apply(rt: Runtime, req: dict[str, Any]) -> None:
    """Called once the request is decided: tells tools-service, or marks the request to try again."""
    await _apply(rt, await registry(rt).request(str(req["id"])))


async def _apply(rt: Runtime, req: dict[str, Any]) -> dict[str, Any]:
    if req["status"] != "approved":
        # A refusal changes nothing in tools-service: its reason stays on this request, read by the run key.
        return req
    body = dict(req["body"])
    decision = {
        "requestId": req["id"],
        "host": body["host"],
        "decision": req["status"],
        "reason": req.get("decision_reason"),
        "by": req.get("decided_by"),
    }
    try:
        if rt.tool_reviews is None:
            raise ServiceUnavailable("tools-service is not configured.", code="tools_unavailable")
        await rt.tool_reviews.egress_host_decision(decision)
        body.pop("applyPending", None)
        body["appliedAt"] = now_iso()
    except Exception:
        body["applyPending"] = True
    await registry(rt).set_body(str(req["id"]), body)
    return {**req, "body": body}
