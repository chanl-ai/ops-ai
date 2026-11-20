"""A v2 workflow version's way to live: a saved draft, a publish request decided in Reviews, live, paused.

The request is the shared publish request (`store/agent_registry.py`, kind `engine`, ids `WFP-`), so Reviews lists
and decides it with the same rules as an agent's or a v1 workflow's: the requester cannot approve it, and rejecting
or returning needs a reason. `publish_reviews.decide` calls `approve` on an approval. "In review" is never stored: a
draft is in review while it has a pending request, so a rejected or returned request leaves it a draft with nothing to
undo. Whether a request needs a second person is the team's publish policy (`publish_policy.decide`), asked
only in `request_publish`.
"""

from __future__ import annotations

from typing import cast

from pydantic import JsonValue

from ops_engine import default_registry
from ops_engine.definition import WorkflowDefinition, validate
from ops_engine.diff import diff
from ops_engine.node_types import list_columns
from ops_engine.store import DefinitionRow, DefinitionStore, DefinitionVersion
from ops_engine.store.definitions import ListColumns
from ops_service_kit import narrow
from ops_service_kit.errors import Conflict, NotFound, Unprocessable
from ops_service_kit.http import Json

from ..store.agent_registry import PublishRequestRow
from ..store.engine import EngineTransactions
from ..store.mailboxes import MailboxStore
from ..store.tenancy import current_team
from .account_names import require_team_accounts, step_names
from .agent_registry import ReviewView, registry, review_view
from .auth import Principal, require_builder
from .deps import Runtime
from .email_trigger import require_binding
from .publish_policy import decide
from .review_sla import sla_hours

KIND = "engine"
REGISTRY = default_registry()


def listed(definition: JsonValue) -> ListColumns:
    """The definition's Workflows list columns, stored with each version it saves."""
    return list_columns(definition, REGISTRY)


def definitions(rt: Runtime) -> DefinitionStore:
    """The v2 definitions, each save writing its list columns (`listed`)."""
    return DefinitionStore(EngineTransactions(rt.db), listed)


async def pending(rt: Runtime, workflow_id: str) -> PublishRequestRow | None:
    """The workflow's open publish request, if any."""
    return next((r for r in await registry(rt).requests(KIND, workflow_id) if r.status == "pending"), None)


def stage_of(version: DefinitionRow | DefinitionVersion, request: PublishRequestRow | None) -> str:
    """A version's stage as the console shows it: its stored stage, or in_review for the draft a request names."""
    if request is not None and version.stage == "draft" and int(request.version) == version.version:
        return "in_review"
    return version.stage


def nodes_of(definition: Json | None) -> dict[str, Json]:
    """A stored definition's nodes by id. The definition is the customer's: read loose, failing as it always has on
    a node that is not an object or names no id."""
    raw = cast(list[Json], (definition or {}).get("nodes") or [])
    return {str(n["id"]): n for n in raw}


def changes(old: Json | None, new: Json) -> list[str]:
    """What a reviewer reads: steps added, removed, changed or moved against the version that serves the workflow now,
    in the words of the editor's diff (`ops_engine.diff`)."""
    if old is None:
        return ["First version"]
    d = diff(old, new)
    out = [f"Added step {s['name']}" for s in d["added"]]
    out += [f"Removed step {s['name']}" for s in d["removed"]]
    out += [f"Changed step {s['name']}" for s in d["changed"]]
    out += [f"Moved step {s['name']}" for s in d["moved"]]
    if d["connected"] or d["disconnected"]:
        out.append("Changed connections")
    out += [f"Changed workflow {f['field']}" for f in d["workflow"]]
    return out or ["No step changed"]


def acts_on(definition: Json) -> list[str]:
    """What each step acts on, as the reviewer must read it: the operation a tool step calls and the review that
    approves it, the agent an agent step runs, the write a review approves. These fields are literals (a `$.` path is
    refused by the type's schema), so this is what the live version calls."""
    out: list[str] = []
    for nid, n in nodes_of(definition).items():
        p = cast(Json, n.get("parameters") or {})
        name = str(n.get("name") or nid)
        if n.get("type") == "ops.action.tool":
            by = f", approved by step {p['approvedBy']}" if p.get("approvedBy") else ""
            out.append(f"Step {name} calls operation {p.get('operation')}{by}")
        elif n.get("type") == "ops.ai.agent":
            out.append(f"Step {name} runs agent {p.get('agent')}")
        elif n.get("type") == "ops.flow.humanReview" and p.get("approves"):
            out.append(f"Step {name} approves the write of step {p['approves']}")
    return out


def require_rights(me: Principal, row: DefinitionRow, action: str) -> None:
    """A stored definition's owning team and saver, checked by the shared rule (auth.require_builder)."""
    require_builder(
        me,
        area="workflows",
        team_id=row.team_id,
        action=action,
        what="this workflow",
    )


async def request_publish(rt: Runtime, me: Principal, workflow_id: str, version: int | None, note: str) -> ReviewView:
    """Opens the publish request for a draft (the newest version when `version` is None) and returns it as a Review.
    Approved at once only where the publish policy says no review is needed, which makes the version live."""
    store = definitions(rt)
    row = await store.row(workflow_id, version, team=current_team())
    if row is None:
        what = f"version {version} of " if version is not None else ""
        raise NotFound(f"{what}workflow definition {workflow_id}")
    require_rights(me, row, "publish")
    if row.stage != "draft":
        raise Conflict(f"v{row.version} is {row.stage}, not a draft.", code="not_a_draft")
    checks = validate(WorkflowDefinition.model_validate(row.definition), REGISTRY)
    if checks:
        raise Unprocessable(
            f"v{row.version} has {len(checks)} failing checks.", code="definition_checks", details={"checks": checks}
        )
    await require_binding(MailboxStore(rt.db), me, row)
    current = await store.serving(workflow_id, team=current_team())
    team = current_team() or (row.team_id or "")
    await require_team_accounts(rt, team, step_names(row.definition))
    req = await open_publish(rt, workflow_id, row, current, by=me.email, team=team, note=note)
    return review_view(req, name=row.name, slug="", sla_hours=await sla_hours(rt))


async def open_publish(
    rt: Runtime,
    workflow_id: str,
    row: DefinitionRow,
    current: DefinitionRow | None,
    *,
    by: str,
    team: str,
    note: str,
) -> PublishRequestRow:
    """The publish request for a checked draft `row` over the live `current`, decided by the team's publishReview read
    now: approved and live at once where no review is needed, otherwise waiting in Reviews. A person's publish and a
    shipped system workflow's update (service_events) both open it here, so neither skips the policy."""
    nodes = len(narrow.json_list(row.definition.get("nodes")))
    body: Json = {
        "workflowId": workflow_id,
        "fromVersion": current.version if current else 0,
        "toVersion": row.version,
        "note": note,
        "requestedBy": by,
        "changes": [
            *changes(current.definition if current else None, row.definition),
            *acts_on(row.definition),
        ],
        # One schema and port check per step, all passing: a definition with a failing check is refused before here.
        "validation": {"passed": nodes, "total": nodes, "regressions": 0, "checksFailing": 0},
        "digest": row.digest,
    }
    decision = await decide(
        rt, area="workflows", team_id=team, old=current.definition if current else None, new=row.definition
    )
    body |= decision.record()
    approved = not decision.review_required
    req = await registry(rt).open_request(
        KIND, workflow_id, row.version, note=note, by=by, body=body, approved=approved
    )
    if approved:
        await approve(rt, req)
    return req


async def view(rt: Runtime, req: PublishRequestRow, *, name: str | None = None) -> ReviewView:
    """The request as the console's Review, named after the version it publishes; `name` when a list read the
    versions together (publish_reviews.all_views)."""
    if name is None:
        row = await definitions(rt).row(str(req.subject_id), int(req.version))
        name = row.name if row else str(req.subject_id)
    return review_view(req, name=name, slug="", sla_hours=await sla_hours(rt))


async def approve(rt: Runtime, req: PublishRequestRow) -> None:
    """An approved request makes its version live and supersedes the one before; a paused workflow stays paused."""
    try:
        await definitions(rt).go_live(str(req.subject_id), int(req.version))
    except LookupError as e:
        raise Conflict(f"{req.subject_id} v{req.version} was deleted before it was approved.") from e
