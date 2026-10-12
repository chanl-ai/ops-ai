"""Agent and workflow publish requests as reviews: the view, the decide rules and the publish an approval runs. The
publish-request routes and the Reviews facade both call these, so a request decided from either place is held to the
same rules: the requester cannot decide, nor can whoever saved an agent version, and rejecting or returning needs a
reason."""

from __future__ import annotations

from typing import Any

from ops_agents.graphs.definition import WorkflowDefinition
from ops_service_kit.errors import Conflict, Forbidden, ValidationFailed

from .agent_registry import go_live, registry, review_view
from .deps import Runtime
from .workflow_registry import publish as publish_workflow
from .workflow_registry import registry as workflow_registry

ID_PREFIXES = ("AGP-", "WFP-")


def is_request_id(review_id: str) -> bool:
    return review_id.startswith(ID_PREFIXES)


async def view(rt: Runtime, req: dict[str, Any]) -> dict[str, Any]:
    if req["kind"] == "agent":
        row = await registry(rt).row(req["subject_id"])
        name = (await registry(rt).version(req["subject_id"], int(req["version"])))["spec"]["name"]
        return review_view(req, name=name, slug=row["slug"])
    row = await workflow_registry(rt).find(req["subject_id"])
    return review_view(req, name=row["name"] if row else req["subject_id"], slug="")


async def get(rt: Runtime, request_id: str) -> dict[str, Any]:
    return await view(rt, await registry(rt).request(request_id))


async def all_views(rt: Runtime) -> list[dict[str, Any]]:
    """Every publish request, pending and decided, for the Reviews list."""
    out: list[dict[str, Any]] = []
    for req in await registry(rt).all_requests():
        try:
            out.append(await view(rt, req))
        except Exception:
            continue
    return out


async def decide(rt: Runtime, approver: str, request_id: str, *, decision: str, reason: str | None) -> dict[str, Any]:
    reg = registry(rt)
    req = await reg.request(request_id)
    if decision not in ("approved", "rejected", "returned"):
        raise ValidationFailed(f"Unknown decision {decision}.")
    if req["status"] != "pending":
        raise Conflict(f"{request_id} was already {req['status']}.", code="already_decided")
    if approver == req["requested_by"]:
        raise Forbidden("You requested this publish, so someone else has to decide it.")
    if req["kind"] == "agent" and approver == req["body"].get("savedBy"):
        raise Forbidden("You saved this version, so someone else has to decide its publish.")
    reason = (reason or "").strip() or None
    if decision != "approved" and reason is None:
        raise ValidationFailed("A reason is required to reject or return.", code="reason_required")
    if not await reg.decide_request(request_id, decision, approver, reason):
        raise Conflict(f"{request_id} was decided by someone else first.", code="already_decided")
    if decision == "approved":
        await _publish(rt, req, approver)
    return await view(rt, await reg.request(request_id))


async def _publish(rt: Runtime, req: dict[str, Any], by: str) -> None:
    subject, version = req["subject_id"], int(req["version"])
    if req["kind"] == "agent":
        reg = registry(rt)
        await reg.publish(subject, version, by=by, review_id=req["id"])
        if not (await reg.row(subject))["paused"]:
            go_live(rt, subject, version, (await reg.version(subject, version))["spec"])
        return
    d = WorkflowDefinition.model_validate(req["body"]["definition"])
    await publish_workflow(rt, subject, d, req["body"]["graph"], note=req["note"], by=by, review_id=req["id"])
