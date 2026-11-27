"""A v2 workflow version's way to live: a saved draft, a publish request decided in Reviews, live, paused.

The request is the shared publish request (`store/agent_registry.py`, kind `engine`, ids `WFP-`), so Reviews lists
and decides it with the same rules as an agent's or a v1 workflow's: the requester cannot approve it, and rejecting
or returning needs a reason. `publish_reviews.decide` calls `approve` on an approval. "In review" is never stored: a
draft is in review while it has a pending request, so a rejected or returned request leaves it a draft with nothing to
undo. Whether a request needs a second person is the team's publish policy (`publish_policy.decide`), asked
only in `request_publish`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, cast

from pydantic import JsonValue

from ops_engine import default_registry
from ops_engine.definition import InvalidDefinitionError, parse, validate
from ops_engine.diff import diff
from ops_engine.node_types import list_columns
from ops_engine.store import DefinitionRow, DefinitionStore, DefinitionVersion
from ops_engine.store.definitions import ListColumns
from ops_service_kit import narrow
from ops_service_kit.errors import ApiError, Conflict, Forbidden, NotFound, Unprocessable
from ops_service_kit.http import Json

from ..store.agent_registry import PublishRequestRow
from ..store.engine import EngineTransactions
from ..store.mailboxes import MailboxStore
from ..store.schedules import WorkflowSchedules
from ..store.tenancy import current_team
from . import ai_steps_gate
from .account_names import require_team_accounts, step_names
from .agent_registry import ReviewView, registry, review_view
from .auth import Principal, require_builder
from .deps import Runtime
from .email_trigger import EMAIL_TRIGGER, require_binding
from .publish_policy import decide, team_document
from .review_sla import sla_hours
from .routers.tool_catalog import directory_tools, known_tools
from .schedule_clock import required_beyond_due

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


@dataclass(frozen=True)
class Blocker:
    """One reason a publish is refused: `check` as the publish dialog lists it (DefinitionCheck's fields), and
    `error`, the refusal the publish answers with when it is the first one."""

    check: Json
    error: ApiError


def _on_trigger(definition: Json) -> str | None:
    """The id of the definition's email trigger step, where a mailbox refusal is fixed."""
    for n in narrow.json_list(definition.get("nodes")):
        if isinstance(n, dict) and n.get("type") == EMAIL_TRIGGER:
            return str(n.get("id") or "") or None
    return None


async def _missing_tools(rt: Runtime, definition: Json) -> list[Blocker]:
    """A tool step whose operation the team's tool list does not offer, read as a skill save reads it
    (`known_tools`, asked again fresh before refusing), so a workflow never publishes a step that cannot run."""
    steps = [
        (nid, str(cast(Json, n.get("parameters") or {}).get("operation") or ""))
        for nid, n in nodes_of(definition).items()
        if n.get("type") == "ops.action.tool"
    ]
    if not steps:
        return []

    # The registry's operations first: they need no store read, and a step naming a workflow is rare, so the
    # workflow rows are read only when a step is still unmatched.
    listed = await directory_tools(rt)
    offered = {t["id"] for t in listed}
    if any(op not in offered for _, op in steps):
        offered = {t["id"] for t in await known_tools(rt, listed=listed)}
    if any(op not in offered for _, op in steps):
        offered = {t["id"] for t in await known_tools(rt, fresh=True)}
    out: list[Blocker] = []
    for nid, op in steps:
        if op and op not in offered:
            # Without a gateway the list is the in-process catalogue, which holds none of the platform's tools
            # (send_reply among them) and no app's, and the runner calls no tool at all; naming the gateway says why.
            message = (
                f"Step {nid} calls {op}, which this team does not have; add the tool or change the step."
                if rt.gateway
                else f"Step {nid} calls {op}, but this install has no tool gateway (OPS_GATEWAY_URL is not set), so "
                "it cannot run tool steps; set the gateway or change the step."
            )
            err = Unprocessable(message, code="tool_not_available", details={"node": nid})
            out.append(
                Blocker(
                    {
                        "node": nid,
                        "level": "error",
                        "code": "tool_not_available",
                        "message": message,
                        "field": "operation",
                    },
                    err,
                )
            )
    return out


async def blockers(
    rt: Runtime, me: Principal, row: DefinitionRow, definition: Json, *, digest: str | None = None
) -> list[Blocker]:
    """Every reason publishing `definition` as a version of `row`'s workflow is refused: a publish request already
    open, its error checks, AI steps while the team has them off, an email trigger on a mailbox the publisher may not
    bind, accounts the team does not have, and with `digest` (the definition as its version would store it) a stored
    version it equals that is no draft. The publish dialog lists them all and the publish refuses on the first, before
    any version is made, so the two cannot differ. Asks platform-service and tools-service, so it runs with no
    transaction open."""
    out: list[Blocker] = []
    if (request := await pending(rt, row.workflow_id)) is not None:
        message = f"Version {request.version} is waiting for review ({request.id}); decide it in Reviews first."
        out.append(
            Blocker(
                {"node": None, "level": "error", "code": "review_open", "message": message},
                Conflict(message, code="review_open"),
            )
        )
    if digest is not None:
        # The store hands back a stored version with this digest instead of making one; only a draft or a superseded
        # version (made again as the next one) can then be published.
        same = next((v for v in reversed(await definitions(rt).versions(row.workflow_id)) if v.digest == digest), None)
        if same is not None and same.stage not in ("draft", "superseded"):
            message = (
                f"These changes are the same as version {same.version}, which is {same.stage}; nothing to publish."
            )
            out.append(
                Blocker(
                    {"node": None, "level": "error", "code": "not_a_draft", "message": message},
                    Conflict(message, code="not_a_draft"),
                )
            )
    try:
        d = parse(definition)
    except InvalidDefinitionError as e:
        check: Json = {"node": None, "level": "error", "code": "invalid_definition", "message": str(e)}
        # The blockers found so far stay: an open review is still the first thing in the way.
        return [*out, Blocker(check, Unprocessable(str(e), code="definition_checks", details={"checks": [check]}))]
    if checks := validate(d, REGISTRY):
        failing = Unprocessable(
            f"The workflow has {len(checks)} failing checks.",
            code="definition_checks",
            details={"checks": cast(JsonValue, checks)},
        )
        out += [Blocker(c, failing) for c in checks]
    out += await _missing_tools(rt, definition)
    team = current_team() or (row.team_id or "")
    # The owning team's policy, as a version is stored under (`_store_version`): a workflow no team owns runs none.
    if (uses := ai_steps_gate.ai_nodes(d, REGISTRY)) and not await ai_steps_gate.allowed(rt, row.team_id):
        err = Unprocessable(ai_steps_gate.OFF, code="ai_steps_off", details={"nodes": cast(JsonValue, uses)})
        out += [
            Blocker({"node": n, "level": "error", "code": "ai_steps_off", "message": ai_steps_gate.OFF}, err)
            for n in uses
        ]
    try:
        await require_binding(MailboxStore(rt.db), me, row.model_copy(update={"definition": definition}))
    except (Unprocessable, Forbidden) as e:
        node = _on_trigger(definition)
        out.append(
            Blocker({"node": node, "level": "error", "code": e.code, "message": e.message, "field": "mailbox"}, e)
        )
    # A saved schedule outlives versions: a version whose scheduled trigger needs more than dueAt would fail every tick.
    for saved in await WorkflowSchedules(rt.db).for_workflow(row.workflow_id):
        if field := required_beyond_due(definition, saved.trigger_step):
            e = Unprocessable(
                f"This workflow runs on a schedule, which sends only dueAt, and the trigger now requires {field}.",
                code="schedule_input_required",
                details={"field": field},
            )
            check = {"node": saved.trigger_step, "level": "error", "code": e.code, "message": e.message, "field": field}
            out.append(Blocker(check, e))
    try:
        await require_team_accounts(rt, team, step_names(definition))
    except Unprocessable as e:
        out.append(Blocker({"node": None, "level": "error", "code": e.code, "message": e.message}, e))
    return out


def refuse(found: list[Blocker]) -> None:
    """Raises the first blocker's refusal; a no-op when there is none."""
    if found:
        raise found[0].error


@dataclass(frozen=True)
class PolicyReads:
    """What opening a publish request reads from platform-service: the publishReview document (None when unread) and
    the review deadline. A publish that makes its version first reads these before it, so a failed read leaves the
    versions and the working copy as they were and the same publish can be sent again."""

    document: Json | None
    sla_hours: float


async def policy_reads(rt: Runtime) -> PolicyReads:
    return PolicyReads(await team_document(rt), await sla_hours(rt))


async def request_publish(
    rt: Runtime,
    me: Principal,
    workflow_id: str,
    version: int | None,
    note: str,
    *,
    checked: bool = False,
    reads: PolicyReads | None = None,
) -> ReviewView:
    """Opens the publish request for a draft (the newest version when `version` is None) and returns it as a Review.
    Approved at once only where the publish policy says no review is needed, which makes the version live. `reads`:
    the policy reads the caller made before making the version (policy_reads)."""
    store = definitions(rt)
    row = await store.row(workflow_id, version, team=current_team())
    if row is None:
        what = f"version {version} of " if version is not None else ""
        raise NotFound(f"{what}workflow definition {workflow_id}")
    require_rights(me, row, "publish")
    if row.stage != "draft":
        raise Conflict(f"v{row.version} is {row.stage}, not a draft.", code="not_a_draft")
    # `checked`: the caller asked `blockers` for this definition a moment ago, before making the version.
    if not checked:
        refuse(await blockers(rt, me, row, row.definition))
    current = await store.serving(workflow_id, team=current_team())
    team = current_team() or (row.team_id or "")
    if reads is None:
        reads = await policy_reads(rt)
    req = await open_publish(rt, workflow_id, row, current, by=me.actor, team=team, note=note, document=reads.document)
    return review_view(req, name=row.name, slug="", sla_hours=reads.sla_hours)


async def open_publish(
    rt: Runtime,
    workflow_id: str,
    row: DefinitionRow,
    current: DefinitionRow | None,
    *,
    by: str,
    team: str,
    note: str,
    document: Json | Literal["read"] | None = "read",
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
        rt,
        area="workflows",
        team_id=team,
        old=current.definition if current else None,
        new=row.definition,
        document=document,
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
