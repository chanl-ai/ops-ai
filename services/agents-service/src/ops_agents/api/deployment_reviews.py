"""Widget deployment changes that wait for a second person: an ordinary publish request of kind `deployment`
in the Reviews flow, decided under `publish_reviews.decide` like every other kind.

Changing a deployment's allowed origins changes who can reach the agent, so the publish policy treats it as an access
change, reviewed under every mode, never included. Moving it to the agent's newest published version follows
the Agents setting as a minor change: that version was reviewed when it was published. What waits is held on the
request and applied when it is approved; the deployment keeps serving as it was until then."""

from __future__ import annotations

from typing import cast

from ops_service_kit import narrow
from ops_service_kit.errors import NotFound
from ops_service_kit.http import Json, JsonValue
from ops_service_kit.ids import now_iso

from ..store.agent_registry import PublishRequestRow
from ..store.widget_deployments import WidgetDeployments
from .agent_registry import ReviewView, registry, review_view
from .deps import Runtime
from .publish_policy import decide
from .review_sla import sla_hours
from .runs import graph_store

KIND = "deployment"


def _store(rt: Runtime) -> WidgetDeployments:
    return WidgetDeployments(graph_store(rt).engine)


def as_policy(origins: list[str], version: int) -> Json:
    """A deployment as the publish policy reads it: origins are access, the pinned version is minor."""
    return {"access": [*sorted(origins)], "pinnedVersion": version}


def _words(changes: Json, before: Json) -> list[str]:
    out: list[str] = []
    if "origins" in changes:
        asked, had = cast(list[str], changes["origins"]), cast(list[str], before["origins"])
        added = sorted(set(asked) - set(had))
        removed = sorted(set(had) - set(asked))
        out += [f"Allow {o}" for o in added] + [f"Stop allowing {o}" for o in removed]
    if changes.get("latest"):
        out.append(
            f"Serve the latest published version (now v{changes['agentVersion']}) instead of v{before['agentVersion']}"
        )
    elif "agentVersion" in changes:
        out.append(f"Serve v{changes['agentVersion']} instead of v{before['agentVersion']}")
    return out


def _pin(changes: Json) -> int | None:
    """The column a version change writes: None when the change is to follow Latest (`latest`), whose `agentVersion`
    is only the version Latest meant when it was asked for, so the policy can judge it."""
    return None if changes.get("latest") else int(cast(int | str | float, changes["agentVersion"]))


async def change(rt: Runtime, row: Json, changes: Json, *, by: str) -> Json:
    """The columns to update now: every change when the policy needs no review, none when it does, in which case a
    request holding them is opened. `row` is the deployment as its store reads it."""
    served: JsonValue = row["agent_version"]
    if served is None:  # on Latest: the version it serves now is the agent's published one
        served = (await registry(rt).row(str(row["agent_id"]))).published_version
    if served is None:  # on Latest with nothing published: refused as reading the version as a number was
        raise TypeError("the deployment's agent has no published version")
    origins: list[str] = list(cast(list[str], row["origins"]))
    version = int(cast(int | str | float, served))
    before: Json = {"origins": [*origins], "agentVersion": version}
    decision = await decide(
        rt,
        area="agents",
        team_id=str(row["team_id"]),
        old=as_policy(origins, version),
        new=as_policy(
            cast(list[str], changes.get("origins", before["origins"])),
            int(cast(int | str | float, changes.get("agentVersion", before["agentVersion"]))),
        ),
    )
    if not decision.review_required:
        return {
            **({"origins": changes["origins"]} if "origins" in changes else {}),
            **({"agent_version": _pin(changes)} if "agentVersion" in changes else {}),
        }
    body: Json = {
        "deploymentId": row["id"],
        "deploymentName": row["name"],
        "teamId": row["team_id"],
        "changes": changes,
        "before": before,
        "words": [*_words(changes, before)],
        "savedBy": by,
        **decision.record(),
    }
    version = int(cast(int | str | float, changes.get("agentVersion", before["agentVersion"])))
    await registry(rt).open_request(KIND, str(row["id"]), version, note="", by=by, body=body, approved=False)
    return {}


async def pending(rt: Runtime, deployment_id: str) -> str | None:
    for req in await registry(rt).all_requests():
        if req.kind == KIND and req.subject_id == deployment_id and req.status == "pending":
            return str(req.id)
    return None


async def team(rt: Runtime, req: PublishRequestRow) -> str | None:
    row = await _store(rt).get(str(req.subject_id))
    return str(row["team_id"]) if row is not None else None


async def view(rt: Runtime, req: PublishRequestRow) -> ReviewView:
    v = review_view(req, name=narrow.required(req.body, "deploymentName", str), slug="", sla_hours=await sla_hours(rt))
    v.pop("publish", None)
    policy = {**v["policy"], "id": "gp_deployment_change", "name": "Widget deployment change"}
    return cast(
        ReviewView,
        {
            **v,
            "title": f"Change {req.body['deploymentName']}",
            "workflowId": "",
            "actionTool": "change_deployment",
            "policy": policy,
            "reasoning": req.body["words"],
        },
    )


async def apply(rt: Runtime, req: PublishRequestRow) -> None:
    store = _store(rt)
    if await store.get(str(req.subject_id)) is None:
        raise NotFound(f"Deployment {req.subject_id}")
    changes = narrow.an_object(req.body["changes"], "the requested changes")
    values: Json = {}
    if "origins" in changes:
        values["origins"] = changes["origins"]
    if "agentVersion" in changes:
        values["agent_version"] = _pin(changes)
    if values:
        await store.update(str(req.subject_id), updated_at=now_iso(), **values)
