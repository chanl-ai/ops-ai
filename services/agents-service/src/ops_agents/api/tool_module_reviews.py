"""Tool module security reviews as ordinary publish requests (c-163): opened by tools-service, decided in Human Tasks
under `publish_reviews.decide`, and applied back in tools-service.

Opening needs two proofs on one call. The person's own credentials name who asked and the team, as on every route; a
tools-service service token in `X-Service-Authorization` vouches for the rest of the body (the version, its changes,
whether it touches security), which a person could otherwise forge to send a security change to their own team. The
team is never read from the body. A copy of an older review (`import_review`) comes from tools-service alone, with a
token scoped to one team, and is refused for any other team.

A decision is applied by calling tools-service with this service's token. When that call fails the request keeps the
decision under `applyPending` and the next read of the request applies it again, so an approval in Reviews always
reaches the module."""

from __future__ import annotations

from typing import Any

from fastapi import Request

from ops_access import can
from ops_identity import Principal as Caller
from ops_service_kit.errors import Forbidden, ServiceUnavailable, Unauthorized, ValidationFailed
from ops_service_kit.ids import now_iso

from .agent_registry import registry, review_view
from .auth import Principal, caller_of
from .deps import Runtime
from .review_sla import sla_hours

KIND = "tool_module"
TOOLS = "service:tools"


async def tools_service(request: Request, header: str | None, tenant_id: str) -> Caller:
    """The tools-service token sent beside the person's credentials; refused unless it is tools-service's, for the same
    tenant."""
    if not header:
        raise Unauthorized("Only tools-service opens a tool module review.", code="service_required")
    svc: Caller = await request.app.state.ops_auth.services.principal(header)
    if svc.sub != TOOLS or (tenant_id and svc.tenant_id != tenant_id):
        raise Forbidden("Only tools-service opens a tool module review.", code="service_required")
    return svc


def _body(input_body: dict[str, Any], *, team: str, saved_by: str) -> dict[str, Any]:
    return {
        "moduleId": input_body["subjectId"],
        "moduleName": input_body["moduleName"],
        "moduleVersion": input_body["moduleVersion"],
        "changes": list(input_body.get("changes") or []),
        # What the version changes since the published one, as tools-service sent it at open (c-204); kept as asked.
        **({"diff": input_body["diff"]} if input_body.get("diff") else {}),
        "security": bool(input_body.get("security", True)),
        "teamId": team,
        "savedBy": saved_by,
    }


async def open_review(rt: Runtime, me: Principal, input_body: dict[str, Any]) -> dict[str, Any]:
    """`me` is the person who asked, from their delegated credentials; the team is theirs, never the body's."""
    named = input_body.get("teamId")
    if named and named != me.team_id:
        raise Forbidden("A review is opened for the team you act in.", code="team_forbidden")
    team = me.team_id or ""
    # Publishing a tool module is the person's to ask for, as on tools-service's own route.
    can(caller_of(me), "tools", "publish", team=team or None, what="this tool module")
    body = _body(input_body, team=team, saved_by=me.email)
    major = int(str(body["moduleVersion"]).split(".")[0])
    return await registry(rt).open_request(
        KIND,
        str(body["moduleId"]),
        major,
        note=str(input_body.get("note") or ""),
        by=me.email,
        body=body,
        approved=False,
    )


async def open_for(rt: Runtime, svc: Caller, input_body: dict[str, Any]) -> dict[str, Any]:
    """A review a service opens with its own token for a person not on the call: tools-service's seed (c-222). Only a
    service holding `tools:publish`, which only tools-service's scope cap allows (Settings.service_scopes), and only a
    tool module of the team its token is scoped to; who asked is the body's `requestedBy`, and the review records that
    the service opened it on their behalf, never that the person did. They still count as the asker, so
    requesterMayDecide applies to them."""
    named = input_body.get("teamId")
    if not svc.team_id or (named and named != svc.team_id):
        raise Forbidden("A review is opened for the team the token is scoped to.", code="team_forbidden")
    can(svc, "tools", "publish", team=svc.team_id, what="this tool module")
    asked = str(input_body.get("requestedBy") or "")
    if not asked:
        raise ValidationFailed("requestedBy names the person the review is opened for.", code="requested_by_required")
    body = _body(input_body, team=svc.team_id, saved_by=asked)
    major = int(str(body["moduleVersion"]).split(".")[0])
    return await registry(rt).open_request(
        KIND,
        str(body["moduleId"]),
        major,
        note=str(input_body.get("note") or ""),
        by=f"{svc.sub.removeprefix('service:')}-service on behalf of {asked}",
        body=body,
        approved=False,
    )


def team(rt: Runtime, req: dict[str, Any]) -> str | None:
    """Security decides a security change; the module's team decides any other."""
    body = req["body"]
    return rt.settings.security_team_id if body.get("security", True) else (body.get("teamId") or None)


async def view(rt: Runtime, req: dict[str, Any]) -> dict[str, Any]:
    if req["body"].get("applyPending"):
        req = await _apply(rt, req)
    body = req["body"]
    v = review_view(req, name=body["moduleName"], slug="", sla_hours=await sla_hours(rt))
    v.pop("publish", None)
    decided_by = "Security" if body.get("security", True) else body.get("teamId", "")
    policy = {**v["policy"], "id": "gp_tool_module_review", "name": "Tool module review", "reviewers": decided_by}
    reasoning = [str(c.get("detail") or c.get("kind") or "") for c in body["changes"]]
    return {
        **v,
        "title": f"Publish {body['moduleName']} v{body['moduleVersion']}",
        "workflowId": "",
        "actionTool": "publish_tool_module",
        "policy": policy,
        "reasoning": reasoning,
        "toolModule": {
            "moduleId": body["moduleId"],
            "version": body["moduleVersion"],
            "applyPending": bool(body.get("applyPending")),
            **({"diff": body["diff"]} if body.get("diff") else {}),
        },
    }


async def apply(rt: Runtime, req: dict[str, Any]) -> None:
    """Called once the request is decided: tells tools-service, or marks the request to try again."""
    await _apply(rt, await registry(rt).request(str(req["id"])))


async def _apply(rt: Runtime, req: dict[str, Any]) -> dict[str, Any]:
    body = dict(req["body"])
    decision = {
        "requestId": req["id"],
        "version": body["moduleVersion"],
        "decision": req["status"],
        "reason": req.get("decision_reason"),
        "by": req.get("decided_by"),
    }
    try:
        if rt.tool_reviews is None:
            raise ServiceUnavailable("tools-service is not configured.", code="tools_unavailable")
        await rt.tool_reviews.review_decision(str(body["moduleId"]), decision)
        body.pop("applyPending", None)
        body["appliedAt"] = now_iso()
    except Exception:
        body["applyPending"] = True
    await registry(rt).set_body(str(req["id"]), body)
    return {**req, "body": body}
