"""Widget deployment changes that wait for a second person (c-139): an ordinary publish request of kind `deployment`
in the Reviews flow, decided under `publish_reviews.decide` like every other kind.

Changing a deployment's allowed origins changes who can reach the agent, so the publish policy treats it as an access
change, reviewed under every mode, never included (c-086). Moving it to the agent's newest published version follows
the Agents setting as a minor change: that version was reviewed when it was published. What waits is held on the
request and applied when it is approved; the deployment keeps serving as it was until then."""

from __future__ import annotations

from typing import Any

from ops_service_kit.errors import NotFound
from ops_service_kit.ids import now_iso

from ..store.widget_deployments import WidgetDeployments
from .agent_registry import registry, review_view
from .deps import Runtime
from .publish_policy import decide
from .review_sla import sla_hours
from .runs import graph_store

KIND = "deployment"


def _store(rt: Runtime) -> WidgetDeployments:
    return WidgetDeployments(graph_store(rt).engine)


def as_policy(origins: list[str], version: int) -> dict[str, Any]:
    """A deployment as the publish policy reads it: origins are access, the pinned version is minor."""
    return {"access": sorted(origins), "pinnedVersion": version}


def _words(changes: dict[str, Any], before: dict[str, Any]) -> list[str]:
    out: list[str] = []
    if "origins" in changes:
        added = sorted(set(changes["origins"]) - set(before["origins"]))
        removed = sorted(set(before["origins"]) - set(changes["origins"]))
        out += [f"Allow {o}" for o in added] + [f"Stop allowing {o}" for o in removed]
    if changes.get("latest"):
        out.append(
            f"Serve the latest published version (now v{changes['agentVersion']}) instead of v{before['agentVersion']}"
        )
    elif "agentVersion" in changes:
        out.append(f"Serve v{changes['agentVersion']} instead of v{before['agentVersion']}")
    return out


def _pin(changes: dict[str, Any]) -> int | None:
    """The column a version change writes: None when the change is to follow Latest (`latest`), whose `agentVersion`
    is only the version Latest meant when it was asked for, so the policy can judge it."""
    return None if changes.get("latest") else int(changes["agentVersion"])


async def change(rt: Runtime, row: dict[str, Any], changes: dict[str, Any], *, by: str) -> dict[str, Any]:
    """The columns to update now: every change when the policy needs no review, none when it does, in which case a
    request holding them is opened."""
    served = row["agent_version"]
    if served is None:  # on Latest: the version it serves now is the agent's published one
        served = (await registry(rt).row(str(row["agent_id"])))["published_version"]
    before: dict[str, Any] = {"origins": list(row["origins"]), "agentVersion": int(served)}
    decision = await decide(
        rt,
        area="agents",
        team_id=str(row["team_id"]),
        old=as_policy(before["origins"], before["agentVersion"]),
        new=as_policy(
            changes.get("origins", before["origins"]), int(changes.get("agentVersion", before["agentVersion"]))
        ),
    )
    if not decision.review_required:
        return {
            **({"origins": changes["origins"]} if "origins" in changes else {}),
            **({"agent_version": _pin(changes)} if "agentVersion" in changes else {}),
        }
    body = {
        "deploymentId": row["id"],
        "deploymentName": row["name"],
        "teamId": row["team_id"],
        "changes": changes,
        "before": before,
        "words": _words(changes, before),
        "savedBy": by,
        **decision.record(),
    }
    version = int(changes.get("agentVersion", before["agentVersion"]))
    await registry(rt).open_request(KIND, str(row["id"]), version, note="", by=by, body=body, approved=False)
    return {}


async def pending(rt: Runtime, deployment_id: str) -> str | None:
    for req in await registry(rt).all_requests():
        if req["kind"] == KIND and req["subject_id"] == deployment_id and req["status"] == "pending":
            return str(req["id"])
    return None


async def team(rt: Runtime, req: dict[str, Any]) -> str | None:
    row = await _store(rt).get(str(req["subject_id"]))
    return str(row["team_id"]) if row is not None else None


async def view(rt: Runtime, req: dict[str, Any]) -> dict[str, Any]:
    v = review_view(req, name=req["body"]["deploymentName"], slug="", sla_hours=await sla_hours(rt))
    v.pop("publish", None)
    policy = {**v["policy"], "id": "gp_deployment_change", "name": "Widget deployment change"}
    return {
        **v,
        "title": f"Change {req['body']['deploymentName']}",
        "workflowId": "",
        "actionTool": "change_deployment",
        "policy": policy,
        "reasoning": req["body"]["words"],
    }


async def apply(rt: Runtime, req: dict[str, Any]) -> None:
    store = _store(rt)
    if await store.get(str(req["subject_id"])) is None:
        raise NotFound(f"Deployment {req['subject_id']}")
    changes = req["body"]["changes"]
    values: dict[str, Any] = {}
    if "origins" in changes:
        values["origins"] = changes["origins"]
    if "agentVersion" in changes:
        values["agent_version"] = _pin(changes)
    if values:
        await store.update(str(req["subject_id"]), updated_at=now_iso(), **values)
