"""Agent, guardrail, skill and workflow publish requests as reviews: the view, the decide rules and the publish an
approval runs. The publish-request routes and the Reviews facade both call these, so a request decided from either
place is held to the same rules: the requester cannot decide, nor can whoever saved the version, and rejecting or
returning needs a reason."""

from __future__ import annotations

from typing import Any

from ops_agents.graphs.definition import WorkflowDefinition
from ops_service_kit.errors import Conflict, NotFound, ValidationFailed
from ops_store import isolation

from . import deployment_reviews, engine_lifecycle, tool_access_reviews, tool_module_reviews
from .agent_registry import go_live, registry, review_view
from .auth import Principal, require_not_own, require_reviews_decide, review_teams
from .deps import Runtime
from .guardrails import guardrails
from .guardrails import publish as publish_guardrail
from .review_sla import sla_hours
from .skills import publish as publish_skill
from .skills import skills
from .widgets import publish as publish_widget
from .widgets import widgets
from .workflow_registry import publish as publish_workflow
from .workflow_registry import registry as workflow_registry

ID_PREFIXES = ("AGP-", "WFP-", "GRP-", "SKP-", "WDP-", "DPR-", "TMP-", "TAR-")
# Kinds whose request names who saved the change; that person never decides it.
SAVED_KINDS = ("agent", "guardrail", "skill", "widget", deployment_reviews.KIND, tool_module_reviews.KIND)


def is_request_id(review_id: str) -> bool:
    return review_id.startswith(ID_PREFIXES)


async def view(
    rt: Runtime,
    req: dict[str, Any],
    *,
    names: dict[tuple[str, int], str] | None = None,
    agents: dict[tuple[str, int], tuple[str, str]] | None = None,
) -> dict[str, Any]:
    """`names`: the workflow versions' names, and `agents` each agent version's name and slug (named_versions), read
    together by a list so a request reads none of its own."""
    if req["kind"] == deployment_reviews.KIND:
        return await deployment_reviews.view(rt, req)
    if req["kind"] == tool_module_reviews.KIND:
        return await tool_module_reviews.view(rt, req)
    if req["kind"] == tool_access_reviews.KIND:
        return await tool_access_reviews.view(rt, req)
    if req["kind"] == "widget":
        v = review_view(req, name=req["body"]["widgetName"], slug=req["subject_id"], sla_hours=await sla_hours(rt))
        v.pop("publish", None)
        policy = {**v["policy"], "id": "gp_widget_publish", "name": "Widget publish"}
        return {
            **v,
            "workflowId": "",
            "actionTool": "publish_widget",
            "policy": policy,
            "reasoning": req["body"]["changes"],
        }
    if req["kind"] == "skill":
        row = await skills(rt).row(req["subject_id"])
        v = review_view(req, name=req["body"]["skillName"], slug=row["slug"], sla_hours=await sla_hours(rt))
        v.pop("publish", None)
        policy = {**v["policy"], "id": "gp_skill_publish", "name": "Skill publish"}
        return {
            **v,
            "workflowId": "",
            "actionTool": "publish_skill",
            "policy": policy,
            "reasoning": req["body"]["changes"],
        }
    if req["kind"] == "guardrail":
        row = await guardrails(rt).row(req["subject_id"])
        # A guardrail publish shows as a publish request; the topics it would block are its reasoning.
        v = review_view(req, name=row["name"], slug=row["slug"], sla_hours=await sla_hours(rt))
        v.pop("publish", None)
        topics = req["body"]["config"]["topics"]
        policy = {**v["policy"], "id": "gp_guardrail_publish", "name": "Guardrail publish"}
        return {**v, "workflowId": "", "actionTool": "publish_guardrail", "policy": policy, "reasoning": topics}
    if req["kind"] == "agent":
        key = (str(req["subject_id"]), int(req["version"]))
        found = agents if agents is not None else await registry(rt).named_versions({key})
        if key not in found:
            raise NotFound(f"Agent {key[0]} version {key[1]}")
        name, slug = found[key]
        return review_view(req, name=name, slug=slug, sla_hours=await sla_hours(rt))
    if req["kind"] == engine_lifecycle.KIND:
        subject = str(req["subject_id"])
        named = None if names is None else names.get((subject, int(req["version"])), subject)
        return await engine_lifecycle.view(rt, req, name=named)
    row = await workflow_registry(rt).find(req["subject_id"])
    return review_view(req, name=row["name"] if row else req["subject_id"], slug="", sla_hours=await sla_hours(rt))


async def get(rt: Runtime, request_id: str) -> dict[str, Any]:
    return await view(rt, await registry(rt).request(request_id))


async def all_views(rt: Runtime) -> list[dict[str, Any]]:
    """Every publish request, pending and decided, for the Reviews list. A tool access request still pending is not
    one: it runs as its system workflow now (c-257), and listing both would show it twice."""
    out: list[dict[str, Any]] = []
    requests = await registry(rt).all_requests()
    pinned = {(str(r["subject_id"]), int(r["version"])) for r in requests if r["kind"] == engine_lifecycle.KIND}
    names = {k: str(row["name"]) for k, row in (await engine_lifecycle.definitions(rt).pinned(pinned)).items()}
    asked = {(str(r["subject_id"]), int(r["version"])) for r in requests if r["kind"] == "agent"}
    agents = await registry(rt).named_versions(asked)
    for req in requests:
        if req["kind"] == tool_access_reviews.KIND and req["status"] == "pending":
            continue
        try:
            out.append(await view(rt, req, names=names, agents=agents))
        except Exception:
            continue
    return out


async def subject_team(rt: Runtime, req: dict[str, Any]) -> str | None:
    """The team that owns what a publish request would ship, which is the team that reviews it; None when no team owns
    it (a seeded record every team sees)."""
    kind, subject = req["kind"], str(req["subject_id"])
    # Read whoever is acting: the owning team decides who may review, so it must be found even from another team.
    if kind == "agent":
        return await registry(rt).owner_team(subject)
    if kind == "guardrail":
        return await guardrails(rt).owner_team(subject)
    if kind == "skill":
        return await skills(rt).owner_team(subject)
    if kind == "widget":
        return await widgets(rt).owner_team(subject)
    if kind == deployment_reviews.KIND:
        return await deployment_reviews.team(rt, req)
    if kind == tool_module_reviews.KIND:
        return tool_module_reviews.team(rt, req)
    if kind == tool_access_reviews.KIND:
        return tool_access_reviews.team(req)
    if kind == engine_lifecycle.KIND:
        row = await engine_lifecycle.definitions(rt).current(subject) or {}
        return str(row.get("team_id") or "") or None
    return await workflow_registry(rt).owner_team(subject)


async def require_publish_reviewer(rt: Runtime, req: dict[str, Any], approver_teams: list[str]) -> None:
    """A reviewer or admin of the owning team decides a publish (c-122 Q3); one no team owns, a reviewer or admin of
    any team."""
    team = await subject_team(rt, req)
    if team is not None:
        require_reviews_decide(approver_teams, team, f"the publish of {req['subject_id']}")
    elif not approver_teams:
        require_reviews_decide(approver_teams, "any team", f"the publish of {req['subject_id']}")


async def require_publish_decider(rt: Runtime, req: dict[str, Any], approver: Principal) -> None:
    """Who decides a publish: a reviewer or admin of the owning team, and not who asked for it or saved the version
    while requesterMayDecide is off (c-186)."""
    await require_publish_reviewer(rt, req, review_teams(approver))
    await require_not_asker(rt, req, approver)


async def require_not_asker(rt: Runtime, req: dict[str, Any], approver: Principal) -> None:
    """Who asked for the publish or saved the version does not decide it while requesterMayDecide is off."""
    saved = req["body"].get("savedBy") if req["kind"] in SAVED_KINDS else None
    require_not_own(
        approver,
        [req["requested_by"], saved],
        team=await subject_team(rt, req),
        what=f"the publish of {req['subject_id']}",
    )


async def decide(
    rt: Runtime,
    approver: Principal,
    request_id: str,
    *,
    decision: str,
    reason: str | None,
) -> dict[str, Any]:
    """Decides a publish request as `approver`, from the teams where they hold reviews.decide (any team for dev)."""
    reg = registry(rt)
    req = await reg.request(request_id)
    if req["kind"] == tool_access_reviews.KIND:
        raise Conflict(
            "Tool access requests are decided in their workflow run now; open it from the module's Access tab.",
            code="decided_in_workflow",
        )
    await require_publish_reviewer(rt, req, review_teams(approver))
    if decision not in ("approved", "rejected", "returned"):
        raise ValidationFailed(f"Unknown decision {decision}.")
    if req["status"] != "pending":
        raise Conflict(f"{request_id} was already {req['status']}.", code="already_decided")
    await require_not_asker(rt, req, approver)
    reason = (reason or "").strip() or None
    if decision != "approved" and reason is None:
        raise ValidationFailed("A reason is required to reject or return.", code="reason_required")
    if not await reg.decide_request(request_id, decision, approver.email, reason):
        raise Conflict(f"{request_id} was decided by someone else first.", code="already_decided")
    # The reviewer holds reviews.decide in the owning team, which need not be the team they act in: the publish reads
    # and writes the record as that team (c-407), as the record's own page would.
    with isolation.scope(isolation.tenant(), await subject_team(rt, req) or isolation.team()):
        if req["kind"] == tool_module_reviews.KIND:
            # tools-service applies every decision, not only an approval: a no withdraws the version or returns it to
            # draft.
            await tool_module_reviews.apply(rt, req)
        elif decision == "approved":
            await _publish(rt, req, approver.email)
        return await view(rt, await reg.request(request_id))


async def _publish(rt: Runtime, req: dict[str, Any], by: str) -> None:
    subject, version = req["subject_id"], int(req["version"])
    if req["kind"] == deployment_reviews.KIND:
        await deployment_reviews.apply(rt, req)
        return
    if req["kind"] == "guardrail":
        await publish_guardrail(rt, req, by)
        return
    if req["kind"] == "skill":
        await publish_skill(rt, req, by)
        return
    if req["kind"] == "widget":
        await publish_widget(rt, req, by)
        return
    if req["kind"] == engine_lifecycle.KIND:
        await engine_lifecycle.approve(rt, req)
        return
    if req["kind"] == "agent":
        reg = registry(rt)
        await reg.publish(subject, version, by=by, review_id=req["id"])
        if not (await reg.row(subject))["paused"]:
            go_live(rt, subject, version, (await reg.version(subject, version))["spec"])
        return
    d = WorkflowDefinition.model_validate(req["body"]["definition"])
    await publish_workflow(rt, subject, d, req["body"]["graph"], note=req["note"], by=by, review_id=req["id"])
