"""The workflow runner's routes (docs/architecture/workflow-runner.md): the node type registry the editor, the validator
and the runner all read, and v2 definitions (YAML or JSON in, JSON stored). Mounted before `workflows.router`, whose
`/v1/workflows/{workflow_id}` would otherwise take `node-types` as an id. v1 definitions stay on /v1/graphs."""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import AsyncGenerator, Iterable
from dataclasses import replace
from typing import Annotated, Any, Literal, TypeAlias, TypedDict, cast

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse, Response
from pydantic import Field, model_validator
from sse_starlette import EventSourceResponse

from ops_access import can, require_view
from ops_access.check import DEFAULT as ACCESS
from ops_agent_kernel.pii import masked
from ops_contracts.errors import Detail, RunError, run_error
from ops_documents_client import DocumentNotFound, DocumentsClient
from ops_engine import default_registry
from ops_engine.definition import InvalidDefinitionError, WorkflowDefinition, advise, parse, validate
from ops_engine.diff import diff as definition_diff
from ops_engine.document_types import pinned, unpinned
from ops_engine.node_types import start_form
from ops_engine.starts import only_from_workflows
from ops_engine.store import (
    REDRIVABLE,
    TERMINAL,
    DefinitionStore,
    DefinitionSummary,
    ListedRun,
    RunStore,
    StaleWorkingCopy,
    WorkflowOwnedError,
    WorkingCopy,
)
from ops_engine.store import DefinitionRow as StoredDefinition
from ops_engine.store import RunRow as StoredRun
from ops_engine.store.definitions import CURRENT, HUMAN_REVIEW
from ops_files_client import FilesClient, FilesRefused
from ops_identity.fastapi import ActingPerson, Tx
from ops_service_kit.errors import (
    ApiError,
    Conflict,
    Forbidden,
    NotFound,
    ServiceUnavailable,
    Unprocessable,
    ValidationFailed,
)
from ops_service_kit.http import Envelope, In, Json, JsonList, JsonValue, LabelledListResult, ListResult, paged
from ops_service_kit.ids import now_iso
from ops_service_kit.listing import ListQuery
from ops_service_kit.logging import get_logger
from ops_service_kit.narrow import a_list, an_object, json_object
from ops_store import isolation

from ...store.actor_names import UNNAMED_WORKFLOW
from ...store.agent_registry import PublishRequestRow, digest_of, refuse_stale
from ...store.definition_list import definitions_page
from ...store.engine import DatabaseError, EngineTransactions
from ...store.events import EventLog
from ...store.mailboxes import MailboxStore
from ...store.template_copies import TemplateCopies
from ...store.tenancy import current_team, current_tenant
from ...store.trigger_events import TriggerEvents
from .. import ai_steps_gate, engine_lifecycle, run_starts, run_story, step_shapes, task_view
from ..account_names import account_uses_in
from ..actors import ActorView, NamedActors, actor_reads, named_actors, started_by_of
from ..agent_registry import ReviewView
from ..agent_registry import registry as agent_registry
from ..auth import (
    Principal,
    approves_own_writes,
    caller,
    caller_of,
    key_scope,
    principal,
    reader_of,
    require_builder,
    require_key_reaches,
    require_runs_cancel,
    require_runs_start,
    started_by,
)
from ..deps import Runtime, runtime
from ..email_trigger import run_again
from ..engine_runs import live_version, start_run
from ..envelope import ok
from ..file_names import named, names_asked_once
from ..publish_policy import decide, team_document
from ..run_story import Decision, decisions_in, files_in, steps_view
from ..schemas import (  # pyright: ignore[reportPrivateImportUsage]
    SSE_RESPONSE,
    DocumentRead,
    Out,
    PublishDecisionFields,
    PublishReview,
)
from ..unattended_sign_in import unattended_sign_in_warnings
from .tool_catalog import known_tools

router = APIRouter(prefix="/v1/workflows", dependencies=[Depends(principal)])

REGISTRY = default_registry()
log = get_logger("ops_agents.api.routers.engine")
Rt: TypeAlias = Annotated[Runtime, Depends(runtime)]  # noqa: UP040 - FastAPI reads Annotated aliases
Me: TypeAlias = Annotated[Principal, Depends(principal)]  # noqa: UP040
# Every read of a workflow, its runs and their steps: the acting team's workflows view cell, the check the agents and
# skills routers use for their reads. Every GET on /v1/workflows and /v1/runs takes it in place of `Me`
# (tests/engine/test_lifecycle_rights.py walks the routers); an API key is not asked and reads only its own runs.
Reader: TypeAlias = Annotated[Principal, Depends(reader_of("workflows"))]  # noqa: UP040


async def starter(me: Annotated[Principal, Depends(caller)], acting: ActingPerson) -> Principal:
    """Who starts a run on POST /v1/runs: a person or an API key as on every other route, or a service starting one for
    the person its X-Acting-For token names (tools-service, for a person signed in to an MCP link). The run records
    that person as its starter; every right is still decided by `can` on the service token, which carries only the cells
    that person holds in the team, so a person without workflows.run starts nothing. A service acting for nobody holds
    no right here: its scopes are dropped, so `can` refuses it as it refuses anyone without the cell."""
    if me.identity is None or me.identity.kind != "service":
        return me
    if acting is None:
        return replace(me, identity=me.identity.model_copy(update={"scopes": []}))
    return replace(me, email=acting.email, name=acting.name or acting.email, sub=acting.sub)


Starter: TypeAlias = Annotated[Principal, Depends(starter)]  # noqa: UP040


class PortView(Out):
    name: str
    connection: str
    label: str


class RetryView(Out):
    attempts: int
    backoff_seconds: list[float]


class OptionalPortView(Out):
    parameter: str
    # The parameter's value as the definition holds it (a string or a boolean); "*" matches any value set.
    value: JsonValue
    port: str


class NodeTypeView(Out):
    id: str
    version: int
    group: str
    label: str
    description: str
    inputs: list[PortView]
    outputs: list[PortView]
    # The list parameter whose entries become the out ports (a review's options); the declared outputs are its default.
    outputs_from: str | None
    # Out ports every instance has besides those outputs_from lists, such as a Switch's otherwise.
    extra_outputs: list[str] = Field(default_factory=list[str])
    # An extra out port the instance has while `parameter` is `value` (a review's `timeout` when it expires).
    optional_outputs: list[OptionalPortView]
    # A declared out port the instance drops while `parameter` is `value` (Run workflow's `started` when it waits).
    outputs_unless: list[OptionalPortView] = Field(default_factory=list[OptionalPortView])
    parameters: dict[str, JsonValue]
    effects: str
    retry: RetryView
    executor: str
    timeout_seconds: float
    # The generated form for `parameters`: field order, and per field its label, widget, help and option source.
    ui: dict[str, JsonValue]
    # Why the acting team cannot add this step now (an AI step while its setting is off); None when it can.
    unavailable: str | None = None


@router.get("/node-types", response_model=Envelope[list[NodeTypeView]])
async def node_types(rt: Rt, me: Reader) -> JSONResponse:
    """Every registered node type at every version: ports with their connection types, parameters as JSON Schema with
    the form generated from them, effects, retry and executor, and why the acting team cannot use one now. No request
    transaction: it reads no row, and the AI-steps policy comes from platform-service."""
    ai_on = await ai_steps_gate.allowed(rt, current_team() or me.team_id or None)
    return ok(
        [
            {
                **t.view(),
                "unavailable": ai_steps_gate.OFF if t.executor == ai_steps_gate.EXECUTOR and not ai_on else None,
            }
            for t in REGISTRY.all()
        ]
    )


class DefinitionInput(In):
    """Exactly one of `yaml` (YAML or JSON text) and `definition` (the parsed object)."""

    yaml: str | None = None
    definition: dict[str, JsonValue] | None = None

    @model_validator(mode="after")
    def _one(self) -> DefinitionInput:
        if (self.yaml is None) == (self.definition is None):
            raise ValueError("send exactly one of yaml and definition")
        return self


class DefinitionCheck(Out):
    # None for a check about the whole definition (no trigger, a connection to a missing node).
    node: str | None
    level: str
    code: str
    message: str
    # The top-level parameter a schema error names, so the editor shows the message under that field; None otherwise.
    field: str | None = None
    # A source path a builder can jump to (`nodes.find.parameters.operation`); None for a whole-definition check.
    path: str | None = None
    # The port an unknown or unconnected check names; None otherwise.
    port: str | None = None
    # What to change so the next validate passes; None when the message already says it.
    suggestion: str | None = None


# What to change for each engine check code, from the existing node/field/message. No new engine semantics.
_CHECK_SUGGESTION = {
    "unknown_type": "Use a type from GET /v1/workflows/node-types.",
    "unknown_type_version": "Pin typeVersion to a registered version of this type.",
    "unknown_port": "Connect a port this node type declares.",
    "unconnected_port": "Connect this out port or remove the node.",
    "invalid_parameter": "Set the named field to a value that matches the type schema.",
    "no_trigger": "Add one trigger node.",
    "many_triggers": "Keep one trigger node.",
    "unreachable": "Connect this node from the trigger.",
    "invalid_definition": "Fix the YAML or JSON so it parses as a schema v2 definition.",
    "duplicate_node": "Give each node its own id.",
    "unknown_node": "Point the connection at a node id in this definition.",
    "unknown_reference": "Point the mapping at a node id in this definition.",
    "join_needs_branches": "Connect at least two steps into this Join.",
    "duplicate_port": "Give each way out its own name.",
}


def _port_in(message: str) -> str | None:
    """The port name an engine check already put in its message (`no out port maybe`, `Out port approve`)."""
    for marker in ("out port ", "in port ", "Out port ", "port "):
        if marker in message:
            rest = message.split(marker, 1)[1]
            return rest.split()[0].rstrip(".") if rest.split() else None
    return None


def enrich_check(check: Json) -> Json:
    """Adds path, port and suggestion from the check the engine already returned. Does not change its meaning."""
    node, field, code, message = check.get("node"), check.get("field"), check.get("code"), check.get("message") or ""
    path = f"nodes.{node}.parameters.{field}" if node and field else (f"nodes.{node}" if node else None)
    return {
        **check,
        "path": check.get("path") or path,
        "port": check.get("port")
        # The engine words every check's message as text.
        or (_port_in(cast(str, message)) if code in {"unknown_port", "unconnected_port", "duplicate_port"} else None),
        "suggestion": check.get("suggestion") or _CHECK_SUGGESTION.get(str(code or "")),
    }


class DefinitionValidation(Out):
    ok: bool
    workflow_id: str | None
    digest: str | None
    checks: list[DefinitionCheck]


class DefinitionWarning(Out):
    node: str
    field: str
    message: str


class DefinitionPublished(Out):
    workflow_id: str
    version: int
    digest: str
    # False when this exact definition was stored before; its version is returned.
    created: bool
    # What the definition leaves out that does not stop it saving, such as a typed review step's missing param.
    warnings: list[DefinitionWarning] = Field(default_factory=list[DefinitionWarning])


Stage: TypeAlias = Literal["draft", "in_review", "live", "paused", "superseded"]  # noqa: UP040


class DefinitionVersion(Out):
    version: int
    digest: str
    created_at: str
    created_by: str
    stage: Stage


class OpenPublishRequest(Out):
    id: str
    version: int
    requested_by: str
    created_at: str


class StartFormView(Out):
    # The adapter that runs it: email (a test email) or form (the trigger's input schema).
    kind: str
    # The start dialog's title and its button.
    title: str
    action: str
    # How a run started this way reads in audit: "test email by <person>".
    via: str
    # The form as JSON Schema; `format: "file"` fields upload or pick files.
    schema_: dict[str, JsonValue] = Field(alias="schema")
    takes_files: bool


class SaveBase(Out):
    """The copy a save is made on: its version and digest (save-base.ts `baseOf` reads it as `baseVersion` and
    `baseDigest`)."""

    version: int
    digest: str


class WorkingCopyView(Out):
    definition: dict[str, JsonValue]
    digest: str
    # The newest version when the copy was first saved.
    base_version: int
    # The checks of the last save; any error stops a version being made from it.
    checks: list[DefinitionCheck]
    updated_at: str
    updated_by: str


class OutdatedCopyView(WorkingCopyView):
    """A working copy made on an older version than the newest, kept so its change is not lost."""

    # The version saved since outside the editor, who saved it and when.
    newer_version: int
    newer_by: str | None
    newer_at: str | None


class DefinitionView(Out):
    workflow_id: str
    name: str
    version: int
    digest: str
    # The shown version's stage; in_review while a publish request for it is open.
    stage: Stage
    definition: dict[str, JsonValue]
    versions: list[DefinitionVersion]
    # The version live runs start on (live or paused); None before the first approval.
    live_version: int | None
    paused: bool
    review: OpenPublishRequest | None
    # When the workflow was archived; None while it is not.
    archived_at: str | None = None
    # How a person starts it by hand, as its trigger declares; None for a trigger only its source starts.
    start_form: StartFormView | None = None
    # What the editor saves to; None until the first change after the newest version.
    working_copy: WorkingCopyView | None = None
    # A copy older than the newest version: shown to its editor read-only, never saved over without their choice.
    outdated_copy: OutdatedCopyView | None = None
    # The copy the next working copy save must name: the working copy, else the newest version.
    save_base: SaveBase


def definitions(rt: Runtime) -> DefinitionStore:
    return engine_lifecycle.definitions(rt)


def _parsed(body: DefinitionInput) -> WorkflowDefinition:
    try:
        return parse(body.yaml if body.yaml is not None else body.definition or {})
    except InvalidDefinitionError as e:
        raise Unprocessable(f"Invalid workflow definition: {e}", code="invalid_definition") from e


@router.post("/definitions/validate", response_model=Envelope[DefinitionValidation])
async def validate_definition(rt: Rt, me: Me, body: DefinitionInput) -> JSONResponse:
    """Per-node checks against the type registry: unknown type or version, unknown port, an out port that leads
    nowhere (End has none), an unreachable node, parameters that do not match the type's schema; and warnings that
    never refuse a save (level `warning`, e.g. a step two branches meet at without a Join). Saves nothing.
    No request transaction: it reads no row, and documents-service is asked for field shapes."""
    raw = body.yaml if body.yaml is not None else body.definition or {}
    d, checks = await _checked(rt, raw, team=current_team() or me.team_id or None)
    errors = [c for c in checks if c["level"] == "error"]
    return ok({"ok": not errors, "workflowId": d and d.id, "digest": d and d.digest(), "checks": checks})


async def _checked(
    rt: Runtime, raw: str | Json, *, team: str | None = None
) -> tuple[WorkflowDefinition | None, list[Json]]:
    """The definition parsed (None when it does not parse) and its checks: the errors that stop a version, then the
    warnings that never do. The validate route and every working copy save answer with this list."""
    try:
        d = parse(raw)
    except InvalidDefinitionError as e:
        return None, [enrich_check({"node": None, "level": "error", "code": "invalid_definition", "message": str(e)})]
    checks = [enrich_check(c) for c in validate(d, REGISTRY)]
    team = team or current_team() or ""
    found = advise(d, REGISTRY) + await step_shapes.field_warnings(rt, team, d)
    warnings = [enrich_check(c) for c in found + await unattended_sign_in_warnings(rt, team, d)]
    return d, checks + warnings


@router.post(
    "/definitions",
    response_model=Envelope[DefinitionPublished],
    status_code=201,
    responses={200: {"model": Envelope[DefinitionPublished], "description": "This definition was stored before"}},
)
async def create_definition(rt: Rt, me: Me, body: DefinitionInput) -> JSONResponse:
    """Stores the definition as the workflow's next version, once it passes every check; the same definition again
    returns its version (200). A definition with failing checks is refused with them in `details.checks`. 403 unless
    the caller is a builder or admin of the team that owns the workflow (the acting team for a new one).
    No request transaction: the AI-steps policy (platform-service) and document types (documents-service) are asked
    between its reads and its write, with none open."""
    d = _parsed(body)
    held = await definitions(rt).row(d.id, team=current_team())
    data = await _store_version(rt, me, d, held)
    return ok(data, status=201 if data["created"] else 200)


async def _store_version(
    rt: Runtime, me: Principal, d: WorkflowDefinition, held: StoredDefinition | None, *, reopen: bool = False
) -> Json:
    """Stores `d` as the next version of a workflow `held` is the newest version of (None for a new one), once it
    passes every check and the AI-steps gate, with its type references pinned; returns the version as
    DefinitionPublished. A new definition and a version made from the working copy both come here; the copy passes
    `reopen`, so a restored older version becomes a new draft instead of returning the superseded one."""
    # A new workflow belongs to the team the caller names, or its own; a dev session acts across teams, so with neither
    # it is refused rather than saved as no team's, which every team would see.
    new_team = current_team() or me.team_id or None
    if held is None and new_team is None:
        raise ValidationFailed(
            "Choose a team with the X-Team-Id header; a workflow belongs to one team.", code="team_required"
        )
    if held is not None:
        engine_lifecycle.require_rights(me, held, "save")
    else:
        require_builder(me, area="workflows", team_id=current_team(), action="save", what="a workflow")
    checks = [enrich_check(c) for c in validate(d, REGISTRY)]
    if checks:
        raise Unprocessable(
            f"The definition has {len(checks)} failing checks.", code="definition_checks", details={"checks": checks}
        )
    owner = held.team_id if held is not None else current_team() or me.team_id or None
    if (uses := ai_steps_gate.ai_nodes(d, REGISTRY)) and not await ai_steps_gate.allowed(rt, owner):
        raise Unprocessable(ai_steps_gate.OFF, code="ai_steps_off", details={"nodes": uses})
    d = await _pinned_types(rt, me, d, held)
    digest = d.digest()
    # An existing workflow keeps its owner, a shared one (no team) included, so a team's builder edits a shared
    # workflow through review instead of being told it is another team's.
    team = held.team_id if held is not None else new_team
    try:
        version, created = await definitions(rt).publish(
            d.id,
            name=d.name or d.id,
            definition=d.wire(),
            digest=digest,
            now=now_iso(),
            by=me.email,
            team=team,
            reopen=reopen,
        )
    except WorkflowOwnedError as e:
        raise Conflict(f"{d.id} is another team's workflow; choose another id.", code="workflow_owned") from e
    acting = team or current_team() or ""
    found = advise(d, REGISTRY) + await step_shapes.field_warnings(rt, acting, d)
    found += await unattended_sign_in_warnings(rt, acting, d)
    advice = [{"node": w["node"], "field": w["field"], "message": w["message"]} for w in found]
    warnings = await task_view.step_warnings(rt, d.wire()) + advice
    return {
        "workflowId": d.id,
        "version": version,
        "digest": digest,
        "created": created,
        "warnings": cast(JsonList, warnings),
    }


async def _pinned_types(
    rt: Runtime, me: Principal, d: WorkflowDefinition, held: StoredDefinition | None
) -> WorkflowDefinition:
    """`d` with each document type it names unpinned set to that type's newest version, as its version is stored."""
    if not (wanted := unpinned(d.wire())):
        return d
    acting = current_team() or (held.team_id if held is not None else None) or me.team_id
    return parse(pinned(d.wire(), await _newest_versions(rt, wanted, team=acting)))


async def _newest_versions(rt: Runtime, type_ids: set[str], *, team: str | None) -> dict[str, int]:
    """Each document type's newest version in documents-service, read as the workflow's team, so the
    saved definition pins it. An unknown type, or one of another team, refuses the save."""
    if not rt.settings.documents_url or team is None:
        raise Unprocessable(
            "Document types are read from documents-service, which this service cannot reach.",
            code="document_type_unreachable",
        )
    documents = DocumentsClient.from_settings(rt.settings, service="agents", scopes=["documents:view"])
    try:
        out: dict[str, int] = {}
        for type_id in sorted(type_ids):
            try:
                found = await documents.document_type(current_tenant(), team, type_id)
            except DocumentNotFound as e:
                raise Unprocessable(f"No document type {type_id} in this team.", code="document_type_not_found") from e
            out[type_id] = int(found["latestVersion"])
        return out
    finally:
        await documents.aclose()


class DefinitionRow(Out):
    workflow_id: str
    name: str
    version: int
    digest: str
    # live or paused once a version is approved (the serving version's stage); before that the latest version's
    # stage, in_review while its publish request is open; archived once archived, whatever its stage.
    status: Literal["draft", "in_review", "live", "paused", "archived"]
    live_version: int | None
    runs: int
    updated_at: str
    updated_by: str


class AccountUses(Out):
    """How many definitions name one account of an app, for the warning before it is renamed: a rename never rewrites
    them, so each keeps the old name and its next publish fails until its step names the new one."""

    drafts: int
    published: int
    workflows: list[str]
    agents: list[str]


@router.get("/definitions/account-uses", response_model=Envelope[AccountUses])
async def account_uses(
    rt: Rt,
    me: Reader,
    _: Tx,
    app: Annotated[str, Query(min_length=1, max_length=120)],
    name: Annotated[str, Query(min_length=1, max_length=200)],
) -> JSONResponse:
    """The team's workflow drafts and published versions, and agents, that name the account `name` of `app`. 403 unless
    the caller may view the team's workflows."""
    found = await account_uses_in(rt, current_team() or me.team_id, app, name)
    return ok(AccountUses(**found).model_dump(by_alias=True))


@router.get("/definitions", response_model=Envelope[ListResult[DefinitionRow]])
async def list_definitions(
    *, rt: Rt, _me: Reader, _: Tx, q: ListQuery, status: Annotated[list[str] | None, Query()] = None
) -> JSONResponse:
    """The team's v2 workflows on the shared list contract, each at its latest version: search over name and id,
    `status` facets (draft, in review, live, paused, archived) under the search and before the status filter, sorted
    by `sortBy` then by the key, a page at a time; an archived workflow is listed only when `status` asks for it.
    v1 workflows stay on /v1/workflows. 403 unless the caller may view the team's workflows."""
    del status  # read from `q.filters`; declared so the document and the SDKs name it
    listed = await definitions_page(rt.db, q)
    rows = [
        DefinitionRow(**{k: v for k, v in r.items() if k != "recent"}).model_dump(by_alias=True) for r in listed["data"]
    ]
    return ok({**listed, "data": rows})


async def pending_requests(rt: Runtime) -> dict[str, PublishRequestRow]:
    """Open publish requests of v2 workflows, by workflow id."""
    rows = await agent_registry(rt).all_requests()
    return {r.subject_id: r for r in rows if r.kind == engine_lifecycle.KIND and r.status == "pending"}


def workflow_status(summary: DefinitionSummary, request: PublishRequestRow | None) -> str:
    """The workflow's stage on a list row: archived once archived, the serving version's (live or paused) once one is
    approved, else in_review while a request is open, else draft."""
    if summary.archived_at:
        return "archived"
    if summary.current_stage:
        return summary.current_stage
    return "in_review" if request is not None else "draft"


class StartSummary(TypedDict):
    """How a definition starts (`start_of`), keys in reply order."""

    kind: JsonValue
    byHand: bool
    takesFiles: bool


class PendingPublish(TypedDict):
    reviewId: str
    toVersion: int
    requestedBy: str


class WorkflowListParts(TypedDict, total=False):
    """What a v2 row of the Workflows list adds when a publish request is open."""

    pendingPublish: PendingPublish


class WorkflowListRow(WorkflowListParts):
    """A v2 workflow as a row of the Workflows list (`v2_workflow_rows`), keys in reply order."""

    id: str
    name: str
    description: str
    teamId: str | None
    trigger: str
    agentSlugs: list[str]
    stepCount: int
    gateCount: int
    runs24h: int
    reviewed24h: int
    openReviews: int
    status: str
    version: int
    updatedAt: str
    deploymentCount: int
    kind: str
    engine: str
    start: StartSummary


def start_of(definition: Json) -> StartSummary:
    """How a definition starts, for the Workflows list and its pickers: the start form's kind, whether a person
    starts it by hand (a declared start form, and not only other workflows), and whether that form takes a file."""
    form = start_form(definition, REGISTRY)
    by_hand = form is not None and not only_from_workflows(definition)
    return {
        "kind": form["kind"] if form else "source",
        "byHand": by_hand,
        "takesFiles": by_hand and bool(form and form["takesFiles"]),
    }


async def v2_workflow_rows(rt: Runtime, since: str) -> list[WorkflowListRow]:
    """Each v2 workflow as a row of the Workflows list (schemas.Workflow, `engine` v2), so the list joins both kinds on
    the server: steps are its nodes, gates its human reviews, the trigger its trigger node's type label; its status is
    the serving version's stage (live or paused), a draft before the first approval, and an open publish request is
    its `pendingPublish`, as for v1. Fields v2 has no counterpart for (agents, reviews, deployments) are empty."""
    out: list[WorkflowListRow] = []
    try:
        found = await definitions(rt).summaries(since=since, team=current_team())
    except DatabaseError as e:  # a database not yet migrated to the runner's tables lists v1 workflows alone
        log.warning("engine_definitions_unavailable", error=type(e).__name__)
        return []
    open_requests = await pending_requests(rt)
    for d in found:
        request = open_requests.get(d.workflow_id)
        stored = d.definition
        nodes = [an_object(n, "a definition's node") for n in a_list(stored.get("nodes") or [], "a definition's nodes")]
        types = [REGISTRY.find(str(n.get("type")), int(cast(int, n.get("typeVersion") or 0))) for n in nodes]
        # The description says what starts it, as a v1 workflow's trigger text does; else the trigger node's type.
        trigger = str(stored.get("description") or "") or next(
            (t.label for t in types if t and t.group == "trigger"), ""
        )
        out.append(
            {
                "id": d.workflow_id,
                "name": d.name,
                "description": str(stored.get("description") or ""),
                "teamId": d.team_id,
                "trigger": trigger,
                "agentSlugs": [],
                "stepCount": len(nodes),
                "gateCount": sum(1 for n in nodes if n.get("type") == HUMAN_REVIEW),
                "runs24h": d.recent,
                "reviewed24h": d.reviewed,
                "openReviews": d.open_reviews,
                "status": workflow_status(d, request),
                "version": d.current_version or 0,
                "updatedAt": d.created_at,
                "deploymentCount": 0,
                "kind": "standard",
                "engine": "v2",
                "start": start_of(stored),
                **(
                    WorkflowListParts(
                        pendingPublish={
                            "reviewId": request.id,
                            "toVersion": request.version,
                            "requestedBy": request.requested_by,
                        }
                    )
                    if request
                    else WorkflowListParts()
                ),
            }
        )
    return out


@router.delete("/definitions/{workflow_id}", status_code=204, response_model=None)
async def delete_definition(rt: Rt, me: Me, _: Tx, workflow_id: str) -> Response:
    """Deletes a draft (every version); a workflow that has run is kept, since its runs are pinned to its versions.
    403 unless the caller is a builder or admin of the owning team."""
    row = await definitions(rt).row(workflow_id, team=current_team())
    if row is None:
        raise NotFound(f"Workflow definition {workflow_id}")
    engine_lifecycle.require_rights(me, row, "delete")
    outcome = await definitions(rt).delete_draft(workflow_id, team=current_team())
    if outcome == "missing":
        raise NotFound(f"Workflow definition {workflow_id}")
    if outcome == "has_runs":
        raise Conflict(
            f"{workflow_id} has runs pinned to its versions, so it cannot be deleted.", code="definition_has_runs"
        )
    # A workflow installed from a template stops counting as the team's copy, so the template can be installed again.
    await TemplateCopies(rt.db).removed_record("workflow", workflow_id)
    return Response(status_code=204)


@router.post("/definitions/{workflow_id}/archive", response_model=Envelope[DefinitionView])
async def archive_definition(rt: Rt, me: Me, _: Tx, workflow_id: str) -> JSONResponse:
    """Archives the workflow: it starts no run of any mode, a trigger no longer serves it, and it leaves the
    lists; its versions and runs are kept. Who may delete the workflow may archive it."""
    return ok(await _archived(rt, me, workflow_id, True))


@router.post("/definitions/{workflow_id}/restore", response_model=Envelope[DefinitionView])
async def restore_definition(rt: Rt, me: Me, _: Tx, workflow_id: str) -> JSONResponse:
    """Restores an archived workflow as it was: the version that served it serves again, live or paused."""
    return ok(await _archived(rt, me, workflow_id, False))


async def _archived(rt: Runtime, me: Principal, workflow_id: str, archived: bool) -> Json:
    row = await definitions(rt).row(workflow_id, team=current_team())
    if row is None:
        raise NotFound(f"Workflow definition {workflow_id}")
    engine_lifecycle.require_rights(me, row, "delete")
    await definitions(rt).set_archived(workflow_id, archived, by=me.email or me.sub, now=now_iso(), team=current_team())
    return await definition_view(rt, me, workflow_id)


class DefinitionShapes(Out):
    workflow_id: str
    version: int
    # Each step's output by the port it leaves by, as JSON Schema; `additionalProperties: false` is a closed shape.
    steps: dict[str, dict[str, dict[str, JsonValue]]]


@router.get("/definitions/{workflow_id}/versions/{version}/shapes", response_model=Envelope[DefinitionShapes])
async def definition_shapes(rt: Rt, _: Reader, workflow_id: str, version: int) -> JSONResponse:
    """What each step of a saved version outputs, by port, before it has run: fixed by its type, built from
    its settings, or read from its document type or operation. A mapping picker reads it. 403 unless the caller may
    view the team's workflows.
    No request transaction: the version is read, then documents-service is asked with none open."""
    row = await definitions(rt).row(workflow_id, version, team=current_team())
    if row is None:
        raise NotFound(f"Workflow definition {workflow_id} version {version}")
    steps = await step_shapes.version_shapes(rt, current_team() or "", row.definition)
    return ok({"workflowId": workflow_id, "version": version, "steps": steps})


@router.get("/definitions/{workflow_id}", response_model=Envelope[DefinitionView])
async def get_definition(rt: Rt, me: Reader, _: Tx, workflow_id: str, version: int | None = None) -> JSONResponse:
    """One definition at a version (its newest when left out), its versions, its open review and its working copy.
    403 unless the caller may view the team's workflows; an API key reads it without its working copy."""
    return ok(await definition_view(rt, me, workflow_id, version))


async def _open_copy(store: DefinitionStore, workflow_id: str, newest: int) -> WorkingCopy | None:
    """The working copy while it was made on the newest version `newest`. One made on an older version (a version saved
    through the API or CLI since) is left out: its next save is refused as stale and made again on the newest."""
    copy = await store.working_copy(workflow_id, team=current_team())
    return copy if copy is not None and copy.base_version >= newest else None


async def definition_view(rt: Runtime, me: Principal, workflow_id: str, version: int | None = None) -> dict[str, Any]:
    store = definitions(rt)
    row = await store.row(workflow_id, version, team=current_team())
    if row is None:
        raise NotFound(f"Workflow definition {workflow_id}")
    request = await engine_lifecycle.pending(rt, workflow_id)
    stored = await store.versions(workflow_id)
    # The serving version is read from the versions listed here, not by a statement of its own: all versions of an id
    # belong to one team, which `row` has already checked, so `serving` would pick the same one.
    current = next((v for v in reversed(stored) if v.stage in CURRENT), None)
    versions = [
        {
            "version": v.version,
            "digest": v.digest,
            "createdAt": v.created_at,
            "createdBy": v.created_by,
            "stage": engine_lifecycle.stage_of(v, request),
        }
        for v in stored
    ]
    review = request and {
        "id": request.id,
        "version": request.version,
        "requestedBy": request.requested_by,
        "createdAt": request.created_at,
    }
    newest = versions[-1] if versions else {"version": row.version, "digest": row.digest}
    viewer = ACCESS.may(caller_of(me), "workflows", "view", team=row.team_id or current_team())
    held = await store.working_copy(workflow_id, team=current_team()) if viewer else None
    copy = held if held is not None and held.base_version >= int(newest["version"]) else None
    # A copy made on an older version than the newest (one saved through the API or CLI since) is kept and shown, so
    # its unpublished change is never lost; saves are made on the newest version.
    outdated = held if held is not None and copy is None else None
    return {
        "workflowId": workflow_id,
        "name": row.name,
        "version": row.version,
        "digest": row.digest,
        "stage": engine_lifecycle.stage_of(row, request),
        "definition": row.definition,
        "versions": versions,
        "liveVersion": current.version if current else None,
        "paused": bool(current and current.stage == "paused"),
        "review": review,
        "archivedAt": row.archived_at,
        "startForm": start_form(row.definition, REGISTRY),
        "workingCopy": copy and _copy_view(copy),
        "saveBase": _save_base(copy) if copy else {"version": newest["version"], "digest": newest["digest"]},
        "outdatedCopy": outdated
        and _copy_view(outdated)
        | {"newerVersion": newest["version"], "newerBy": newest.get("createdBy"), "newerAt": newest.get("createdAt")},
    }


def _copy_view(copy: WorkingCopy) -> Json:
    return {
        "definition": copy.definition,
        "digest": copy.digest,
        "baseVersion": copy.base_version,
        "checks": copy.checks,
        "updatedAt": copy.updated_at,
        "updatedBy": copy.updated_by,
    }


def _save_base(copy: WorkingCopy) -> Json:
    return {"version": copy.base_version, "digest": copy.digest}


class WorkingCopyInput(In):
    """The definition as the editor holds it, and the copy it was made on (`saveBase` of the view last read)."""

    definition: dict[str, JsonValue]
    base_version: int
    base_digest: str
    # The digest of another person's outdated copy (the view's `outdatedCopy`) this save replaces; a save on the
    # newest version without it is refused with 409 `stale_base` while that copy is kept.
    replaces_digest: str | None = None


class WorkingCopySaved(Out):
    working_copy: WorkingCopyView
    # What the next save names.
    save_base: SaveBase


async def _editable(rt: Runtime, me: Principal, workflow_id: str) -> StoredDefinition:
    """The workflow's newest version, for a person who may change it: 404 when the acting team cannot see it, 403
    without the save right in its team (a viewer, a reviewer)."""
    row = await definitions(rt).row(workflow_id, team=current_team())
    if row is None:
        raise NotFound(f"Workflow definition {workflow_id}")
    engine_lifecycle.require_rights(me, row, "save")
    return row


@router.put("/definitions/{workflow_id}/working-copy", response_model=Envelope[WorkingCopySaved])
async def save_working_copy(rt: Rt, me: Me, workflow_id: str, body: WorkingCopyInput) -> JSONResponse:
    """Saves the editor's working copy as it is, failing checks and all, and answers with its checks. It makes no
    version: publishing does. 409 `stale_base` when `baseVersion` and `baseDigest` are not the newest copy, with who
    saved it and when: read the workflow again and repeat the change. No request transaction: documents-service is
    asked for field shapes before the write."""
    held = await _editable(rt, me, workflow_id)
    definition: Json = {**body.definition, "id": workflow_id}
    _, checks = await _checked(rt, definition, team=held.team_id)
    base = (body.base_version, body.base_digest)
    try:
        copy = await definitions(rt).put_working_copy(
            workflow_id,
            definition=definition,
            digest=digest_of(definition),
            checks=checks,
            base=base,
            now=now_iso(),
            by=me.email,
            replaces=body.replaces_digest,
        )
    except StaleWorkingCopy as e:
        refuse_stale(base, e.version, e.digest, saved_by=e.saved_by, saved_at=e.saved_at)
        raise
    except LookupError as e:
        raise NotFound(f"Workflow definition {workflow_id}") from e
    return ok({"workingCopy": _copy_view(copy), "saveBase": _save_base(copy)})


async def _publish_copy(rt: Runtime, me: Principal, workflow_id: str, base: tuple[int, str], note: str) -> ReviewView:
    """Makes the next version from the working copy saved on `base`, opens its publish request and removes the copy.
    Every refusal comes first, so a refused publish leaves the versions and the copy as they were: the publish right,
    a stale base, then each blocker the publish preview lists."""
    held = await _editable(rt, me, workflow_id)
    engine_lifecycle.require_rights(me, held, "publish")
    store = definitions(rt)
    copy = await store.working_copy(workflow_id, team=current_team())
    if copy is None:
        raise Conflict("There are no unpublished changes to make a version from.", code="nothing_to_publish")
    if copy.base_version < held.version:
        refuse_stale(base, held.version, held.digest, saved_by=held.created_by, saved_at=held.created_at)
    refuse_stale(base, copy.base_version, copy.digest, saved_by=copy.updated_by, saved_at=copy.updated_at)
    d, found = await _publishable(rt, me, held, copy.definition)
    engine_lifecycle.refuse(found)
    # Read before the version is made: a failure after it would leave a draft the copy is outdated behind.
    reads = await engine_lifecycle.policy_reads(rt)
    data = await _store_version(rt, me, cast(WorkflowDefinition, d), held, reopen=True)
    version = cast(int, data["version"])
    review = await engine_lifecycle.request_publish(rt, me, workflow_id, version, note, checked=True, reads=reads)
    # Removed only once the request is open; a save made since stays, as a change on the new version.
    if not await store.drop_working_copy(workflow_id, digest=copy.digest):
        await store.rebase_working_copy(workflow_id, version)
    return review


async def _publishable(
    rt: Runtime, me: Principal, held: StoredDefinition, definition: Json
) -> tuple[WorkflowDefinition | None, list[engine_lifecycle.Blocker]]:
    """`definition` as its version would be stored (document types pinned; None when it does not parse), and every
    blocker to publishing it. The preview and the publish both read this, so the dialog lists each refusal the
    publish can give."""
    try:
        d = parse(definition)
    except InvalidDefinitionError:
        return None, await engine_lifecycle.blockers(rt, me, held, definition)
    pin: list[engine_lifecycle.Blocker] = []
    try:
        d = await _pinned_types(rt, me, d, held)
    except Unprocessable as e:
        pin.append(engine_lifecycle.Blocker({"node": None, "level": "error", "code": e.code, "message": e.message}, e))
    return d, pin + await engine_lifecycle.blockers(rt, me, held, definition, digest=None if pin else d.digest())


# A side of a comparison: a version number, `live` or `working-copy`.
DIFF_SIDE = r"^(\d+|live|working-copy)$"


async def _side(rt: Runtime, workflow_id: str, side: str) -> Json | None:
    """A definition to compare: a version number, `live` (None before the first publish) or `working-copy` (the
    newest version while there is none). 404 for a version the acting team cannot see."""
    store = definitions(rt)
    if side == "live":
        live = await store.serving(workflow_id, team=current_team())
        return live.definition if live else None
    if side == "working-copy":
        newest = await store.row(workflow_id, team=current_team())
        copy = await _open_copy(store, workflow_id, newest.version) if newest else None
        if copy is not None:
            return copy.definition
        row = await store.row(workflow_id, team=current_team())
    else:
        row = await store.row(workflow_id, int(side), team=current_team())
    if row is None:
        raise NotFound(f"{side if side.isdigit() else 'A version'} of workflow definition {workflow_id}")
    return row.definition


class FieldChangeView(Out):
    # `name`, `type`, `typeVersion`, `onError`, or `parameters.<key>` for one of the step's settings.
    field: str
    before: JsonValue = None
    after: JsonValue = None


class StepRefView(Out):
    id: str
    name: str
    type: str


class StepChangeView(StepRefView):
    fields: list[FieldChangeView]


class DefinitionDiffView(Out):
    added: list[StepRefView]
    removed: list[StepRefView]
    changed: list[StepChangeView]
    # Steps that only moved on the canvas.
    moved: list[StepRefView]
    connected: list[str]
    disconnected: list[str]
    workflow: list[FieldChangeView]


@router.get("/definitions/{workflow_id}/diff", response_model=Envelope[DefinitionDiffView])
async def diff_definitions(
    rt: Rt,
    me: Reader,
    workflow_id: str,
    from_: Annotated[str, Query(alias="from", pattern=DIFF_SIDE)],
    to: Annotated[str, Query(pattern=DIFF_SIDE)],
) -> JSONResponse:
    """The steps added, removed, changed (every setting that differs, old and new) and moved between two versions of
    a workflow, its live version or its working copy. 403 unless the caller may view the team's workflows."""
    row = await definitions(rt).row(workflow_id, team=current_team())
    if row is None:
        raise NotFound(f"Workflow definition {workflow_id}")
    # An API key reads the team's versions, never a person's unpublished working copy, as on GET /definitions/{id}.
    if "working-copy" in (from_, to):
        can(caller_of(me), "workflows", "view", team=row.team_id or current_team(), what="this workflow's working copy")
    return ok(definition_diff(await _side(rt, workflow_id, from_), await _side(rt, workflow_id, to) or {}))


class PublishPreview(PublishDecisionFields):
    """What publishing the working copy (or the newest draft, without one) would do."""

    # The version live runs use now; None before the first publish.
    live_version: int | None
    # The working copy's changes against that live version.
    changes: DefinitionDiffView
    # The errors that stop the publish; empty when it can go.
    blockers: list[DefinitionCheck]


@router.get("/definitions/{workflow_id}/publish-preview", response_model=Envelope[PublishPreview])
async def publish_preview(rt: Rt, me: Reader, workflow_id: str) -> JSONResponse:
    """What a publish of the working copy would change, what stops it (each error check), and whether the team's
    publish policy would wait for a review; a change of step positions alone needs none. Nothing is made or opened.
    No request transaction: the policy is read from platform-service."""
    row = await definitions(rt).row(workflow_id, team=current_team())
    if row is None:
        raise NotFound(f"Workflow definition {workflow_id}")
    engine_lifecycle.require_rights(me, row, "publish")
    store = definitions(rt)
    copy = await _open_copy(store, workflow_id, row.version)
    live = await store.serving(workflow_id, team=current_team())
    new = copy.definition if copy else row.definition
    # Decided on the definition as its version will store it, as open_publish decides: a copy the editor saved without
    # its defaults filled in would otherwise differ from the live version in more than step positions.
    with contextlib.suppress(InvalidDefinitionError):
        new = parse(new).wire()
    _, found = await _publishable(rt, me, row, copy.definition if copy else row.definition)
    old = live.definition if live else None
    decision = await decide(
        rt,
        area="workflows",
        team_id=row.team_id or current_team() or "",
        old=old,
        new=new,
        document=await team_document(rt),
    )
    return ok(
        decision.record()
        | {
            "liveVersion": live.version if live else None,
            "changes": definition_diff(old, new),
            "blockers": [enrich_check(b.check) for b in found],
        }
    )


class DefinitionPublishInput(In):
    # The draft to publish; the newest version when left out.
    version: int | None = None
    note: str = Field(default="", max_length=2000)
    # The working copy to publish, as `saveBase` named it when it was read: its next version is made and its request
    # opened in one call, refused before anything is made while a blocker remains. Both or neither, with no `version`.
    base_version: int | None = None
    base_digest: str | None = None

    @model_validator(mode="after")
    def _one_source(self) -> DefinitionPublishInput:
        if (self.base_version is None) != (self.base_digest is None):
            raise ValueError("baseVersion and baseDigest go together")
        if self.base_version is not None and self.version is not None:
            raise ValueError("Name a draft's version or the working copy's base, not both")
        return self


@router.post("/definitions/{workflow_id}/publish-requests", response_model=Envelope[PublishReview], status_code=201)
async def request_definition_publish(rt: Rt, me: Me, workflow_id: str, body: DefinitionPublishInput) -> JSONResponse:
    """Opens a publish request for a draft in Reviews; the version goes live when a second person approves it (at once
    under the dev auto-approve setting). 409 when the version is not a draft or a request is already open, 422 when it
    no longer passes its checks, 403 unless the caller is a builder or admin of the owning team (an admin for a
    workflow no team owns). With `baseVersion` and `baseDigest` it publishes the working copy: every blocker the
    publish preview lists refuses it (422, or 403 for a mailbox the caller may not watch) before any version is made,
    then the next version is made and its request opened. The request lists what each step acts on: its operation,
    agent and approver.
    No request transaction: the team's accounts (tools-service) and the review deadline (platform-service) are asked
    with none open."""
    if body.base_version is not None and body.base_digest is not None:
        return ok(
            await _publish_copy(rt, me, workflow_id, (body.base_version, body.base_digest), body.note), status=201
        )
    return ok(await engine_lifecycle.request_publish(rt, me, workflow_id, body.version, body.note), status=201)


async def set_paused(rt: Runtime, me: Principal, workflow_id: str, paused: bool) -> Json:
    row = await definitions(rt).row(workflow_id, team=current_team())
    if row is None:
        raise NotFound(f"Workflow definition {workflow_id}")
    engine_lifecycle.require_rights(me, row, "pause" if paused else "resume")
    if await definitions(rt).set_paused(workflow_id, paused, team=current_team()) is None:
        raise Conflict(f"{workflow_id} has no live version to {'pause' if paused else 'resume'}.", code="not_live")
    return await definition_view(rt, me, workflow_id)


@router.post("/definitions/{workflow_id}/pause", response_model=Envelope[DefinitionView])
async def pause_definition(rt: Rt, me: Me, _: Tx, workflow_id: str) -> JSONResponse:
    """Stops new live runs of the workflow; runs under way keep going on their version. 409 before any is live; 403
    unless the caller is a builder or admin of the owning team (an admin for a workflow no team owns)."""
    return ok(await set_paused(rt, me, workflow_id, True))


@router.post("/definitions/{workflow_id}/resume", response_model=Envelope[DefinitionView])
async def resume_definition(rt: Rt, me: Me, _: Tx, workflow_id: str) -> JSONResponse:
    """Live runs start again on the live version. 409 before any is live; 403 as for pause."""
    return ok(await set_paused(rt, me, workflow_id, False))


class OptionView(Out):
    value: str
    label: str
    description: str


# How the mailbox picker names each kind of mailbox.
MAILBOX_KINDS = {"gmail": "Gmail", "imap": "IMAP", "graph": "Microsoft 365", "dev": "Dev folder"}

OptionSource: TypeAlias = Literal["agents", "tools", "workflows", "mailboxes"]  # noqa: UP040


@router.get("/option-sources", response_model=Envelope[list[OptionView]])
async def option_sources(rt: Rt, me: Me, source: OptionSource) -> JSONResponse:
    """The choices a node form offers for a field with an option source (`ui.fields.*.source`): published agents,
    registry operations, live v2 workflows, the acting team's mailboxes (Channels > Email). `steps` comes from
    the definition being edited; `knowledge` is not served yet, since no built node type reads a knowledge base.
    403 for agents, tools or workflows without that area's view cell, as its own list answers.
    No request transaction: the tools source is asked of tools-service."""
    options: list[dict[str, str]]
    if source != "mailboxes":
        require_view(caller_of(me), source)
    if source == "mailboxes":
        # The team the caller acts in (X-Team-Id), also for a dev-password session, which reads across teams.
        found = await MailboxStore(rt.db).list(team=me.team_id) if me.team_id else []
        options = [
            {
                "value": m.address,
                "label": m.name or m.address,
                "description": f"{m.address} · {MAILBOX_KINDS[m.provider]}{' · paused' if m.paused else ''}",
            }
            for m in found
        ]
    elif source == "agents":
        agents = [a for a in await agent_registry(rt).rows() if a.published_version is not None]
        options = [{"value": a.id, "label": a.slug, "description": f"Published v{a.published_version}"} for a in agents]
    elif source == "tools":
        tools = [t for t in await known_tools(rt) if not str(t["id"]).startswith("workflow:")]
        options = [
            {"value": t["id"], "label": t["name"], "description": str(t.get("description") or "")} for t in tools
        ]
    else:
        live = [d for d in await definitions(rt).summaries(team=current_team()) if d.current_stage == "live"]
        options = [{"value": d.workflow_id, "label": d.name, "description": f"Live v{d.current_version}"} for d in live]
    return ok(sorted(options, key=lambda o: o["label"].lower()))


# ── Runs (workflow-runner.md section 5): the API only enqueues; a worker runs them. ──


runs_router = APIRouter(prefix="/v1/runs", dependencies=[Depends(principal)])
# POST /v1/runs alone: it also takes a service starting a run for a person (`starter`), which the router-wide
# `principal` above refuses.
run_start_router = APIRouter(prefix="/v1/runs")
POLL_SECONDS = 0.25


class EngineRunInput(In):
    workflow_id: str
    # The version to pin: the live version when left out, or the latest in test mode. A live run starts only on the
    # live version; test mode starts any version, a draft included.
    version: int | None = None
    input: dict[str, Any] = Field(default_factory=dict[str, Any])
    # The caller's key for what started the run; a repeated key returns the first run. A new key when left out.
    run_key: str | None = Field(default=None, max_length=200)
    mode: Literal["live", "test"] = "live"
    # Hold the start work row until then on the database clock (ops.trigger.schedule). 0 is due now.
    after_seconds: float = 0


class RunStarted(Out):
    run_id: str
    workflow_id: str
    version: int
    digest: str
    status: str
    # False when the run key had started a run already; that run is returned.
    created: bool


class RunWaiting(Out):
    node: str
    iteration: int
    payload: dict[str, JsonValue]


class RunFailure(Out):
    """Why a run failed, in the one error model (ops_contracts.errors): a kind, a stable code, the builder's
    message, a sentence safe for a customer and whether a retry helps, with the failing step and attempt."""

    kind: Literal["input", "refused", "upstream", "timeout", "internal"]
    code: str
    message: str
    user_message: str
    retryable: bool
    retry_after_seconds: float | None = None
    node_id: str | None = None
    node_name: str | None = None
    attempt: int | None = None
    of: int | None = None
    trace_id: str | None = None
    # What to do next, for the builder: Retry, Redrive from the failed step, or fix the step.
    suggestion: str | None = None
    # The error's plain values: which clock ran out, which End the run reached, a code the table did not know.
    details: dict[str, Detail] = Field(default_factory=dict)


class RunRow(Out):
    id: str
    # The display name of the workflow version the run is on, in the list; the id when it has none.
    workflow_name: str | None = None
    # Whether the caller may cancel it now: runs/cancel on an unfinished run.
    can_cancel: bool | None = None
    # Whether the caller may retry it now: a Stuck run, by whoever may cancel it.
    can_retry: bool | None = None
    # Whether the caller may redrive it now: a Failed or Stuck run, by whoever may cancel it.
    can_redrive: bool | None = None
    workflow_id: str
    version: int
    digest: str
    mode: str
    status: str
    outcome: str | None
    # The outcome as people read it ("Documents read"), run_story.words over `outcome`.
    outcome_text: str | None = None
    error: str | None
    input: dict[str, JsonValue] | None
    output: JsonValue
    waiting: RunWaiting | None
    created_by: str
    # Who or what started it, named: a person, a mailbox, another workflow's run, an agent or an API key.
    started_by: ActorView | None = None
    created_at: str
    updated_at: str
    finished_at: str | None


class StepAttempt(Out):
    attempt: int
    status: str
    effects: str
    key: str
    port: str | None
    input: JsonValue
    output: JsonValue
    error: str | None
    started_at: str
    finished_at: str | None


class EngineRunStep(Out):
    node_id: str
    iteration: int
    # The last attempt's: what the node returned, through which port, or its error.
    status: str
    port: str | None
    input: JsonValue
    output: JsonValue
    error: str | None
    attempts: list[StepAttempt]


class RunResult(Out):
    # The End step the run finished on, its name in the definition, the outcome it named and its output.
    node: str | None
    name: str | None
    outcome: str
    output: JsonValue


class RunChild(Out):
    """A run a step started (Start workflow, once or for each item), with where it is now."""

    node_id: str
    index: int
    run_id: str
    status: str
    outcome: str | None


class RunFile(Out):
    id: str
    # The name the input gave it alongside the id (`{fileId, name}`), else files-service's; None when neither says.
    name: str | None


class RunDecision(Out):
    """A person's decision at a Human Task step: who, when and why, and the task it was made on."""

    node_id: str
    iteration: int
    # The Human Task's id, as Human Tasks lists it: the run, the step and its iteration.
    review_id: str
    action: str
    reason: str | None
    by: ActorView | None
    at: str | None


class StoryAttachment(Out):
    file_id: str
    name: str
    type: str | None
    size: int | None


class StorySkipped(Out):
    name: str
    # Why the mailbox did not store it, in words.
    message: str


class StoryBodyFile(Out):
    file_id: str
    name: str


class StoryEmail(Out):
    """The email a run began with (its trigger is Email received), from its input (ops_engine shapes.EMAIL)."""

    from_: str = Field(alias="from")
    subject: str
    received_at: str | None
    body: str
    mailbox: str | None
    attachments: list[StoryAttachment]
    skipped: list[StorySkipped]
    body_file: StoryBodyFile | None


class StoryRead(Out):
    """An Extract from file step's read, as the read check draws it."""

    node_id: str
    # The step's name in the workflow.
    name: str
    read: DocumentRead


class StoryFact(Out):
    label: str
    value: str


class StoryCase(Out):
    case_id: str
    subject: str
    customer: str | None
    # The case's own fields, worded.
    facts: list[StoryFact]


class StoryTask(Out):
    review_id: str
    title: str
    open: bool
    # The option chosen, as its label reads; None while open.
    decision: str | None
    # "Hold or flag · waiting for Maya Okafor", "Hold or flag: Hold by Maya Okafor".
    state: str


class StoryChild(Out):
    """A run a step started, as a person reads it: what it was about, where it is now, its case and Human Task."""

    run_id: str
    node_id: str
    index: int
    workflow_name: str
    step_name: str
    # The step's label for its item, else the item's first text that is not an id, else the workflow's name.
    label: str
    status: str
    outcome: str | None
    # The End step it finished on, by name; None until it succeeds.
    ending: str | None
    # Where it is now, in words.
    state: str
    cases: list[StoryCase]
    tasks: list[StoryTask]


class StoryLine(Out):
    """One thing a run did, as a sentence a person reads; the case feed is made of the same lines."""

    at: str | None
    # person, automation or email: what the feed's filters narrow by.
    source: str
    # Who did it: a person's or key's name, the email's sender, or the workflow's name for automation.
    actor: str
    text: str
    # The run, file, case or Human Task the line is about.
    href: str | None


class RunStory(Out):
    email: StoryEmail | None
    reads: list[StoryRead]
    children: list[StoryChild]
    # Runs past the first 50 a step started, counted and not told.
    children_more: int
    # What the run did, oldest first.
    lines: list[StoryLine]


class RunDetail(RunRow):
    steps: list[EngineRunStep]
    # Structured projection of `error` plus the failing step, when one is known. Older clients keep reading `error`.
    failure: RunFailure | None = None
    # Set once the run reached an End, a failure End too: what that End returned.
    result: RunResult | None
    # The runs its steps started, in step and item order, each with its status (a For each step), read here so the
    # run page lists them without asking for each one.
    children: list[RunChild] = Field(default_factory=list[RunChild])
    # The files the run was given, in the order its input names them, so the run page links each by name.
    files: list[RunFile] = Field(default_factory=list[RunFile])
    # Each Human Task decided in this run, in step order, with the person named.
    decisions: list[RunDecision] = Field(default_factory=list[RunDecision])
    # The run told from its steps' output shapes: the email, each read, each run it started.
    story: RunStory | None = None


def runs(rt: Runtime) -> RunStore:
    return RunStore(EngineTransactions(rt.db))


async def visible_run(rt: Runtime, run_id: str, me: Principal | None = None) -> StoredRun:
    """The run, if the selected team may see it: the same team scoping as the run list, and for a scoped API key its
    own workflow's runs only. Another team's run is not found rather than forbidden, so its id reveals
    nothing."""
    run = await runs(rt).row(run_id)
    team = current_team()
    if run is None or (team is not None and run.team_id != team):
        raise NotFound("Run")
    if me is not None and (scope := key_scope(me)) is not None and scope != ("workflow", run.workflow_id):
        raise NotFound("Run")
    return run


def can_retry(me: Principal, run: StoredRun) -> bool:
    """Retry for the caller: a Stuck run, by whoever may cancel it."""
    return run.status == "stuck" and can_cancel(me, run)


def can_redrive(me: Principal, run: StoredRun) -> bool:
    """Redrive for the caller: a Failed or Stuck run, by whoever may cancel the run."""
    if run.status not in REDRIVABLE:
        return False
    try:
        require_runs_cancel(me, team_id=run.team_id, started_by=run.created_by, what="this run")
    except ApiError:
        return False
    return True


def can_cancel(me: Principal, run: StoredRun) -> bool:
    """runs/cancel for the caller on an unfinished run, by the rule the cancel route applies."""
    if run.status in ("succeeded", "failed", "cancelled"):
        return False
    try:
        require_runs_cancel(me, team_id=run.team_id, started_by=run.created_by, what="this run")
    except ApiError:
        return False
    return True


class RunFailureView(TypedDict):
    """Why a run failed (`run_failure`), keys in reply order."""

    kind: str
    code: str
    message: str
    userMessage: str
    retryable: bool
    retryAfterSeconds: float | None
    nodeId: str | None
    nodeName: str | None
    attempt: int | None
    of: int | None
    traceId: str | None
    suggestion: str
    details: dict[str, Detail]


class RunWaitingView(TypedDict):
    node: JsonValue
    iteration: JsonValue
    payload: JsonValue


class RunView(TypedDict):
    """A run as its routes return it (`run_view`), keys in reply order."""

    id: str
    workflowId: str
    version: int
    digest: str
    mode: str
    status: str
    outcome: str | None
    outcomeText: str | None
    error: str | None
    input: JsonValue
    output: JsonValue
    waiting: RunWaitingView | None
    createdBy: str
    createdAt: str
    updatedAt: str
    finishedAt: str | None


class RunStartedView(TypedDict):
    """A run just started (`started_view`), keys in reply order."""

    runId: str
    workflowId: str
    version: int
    digest: str
    status: str
    created: bool


class StartedRun(TypedDict):
    """A run a step started, with its status now (`started_runs`)."""

    nodeId: str
    index: int
    runId: str
    status: str
    outcome: str | None


class RunResultView(TypedDict):
    """The End a run finished on, with its outcome and output (`run_result`)."""

    node: JsonValue
    name: str | None
    outcome: JsonValue
    output: JsonValue


def run_failure(run: StoredRun, steps: list[Json]) -> RunFailureView | None:
    """The run's error as the error model recorded it. A run that failed before the record existed (agents
    migration 0124) reads as `stuck` when it is Stuck and `internal_error` otherwise, with the last failing step."""
    if not run.error:
        return None
    if run.failure:
        err = RunError.model_validate(run.failure)
    else:
        failed = next((s for s in reversed(steps) if s.get("error")), None)
        attempts = list(cast(Iterable[JsonValue], (failed or {}).get("attempts") or []))
        node = (failed or {}).get("nodeId")
        err = run_error(
            "stuck" if run.status == "stuck" else "internal_error",
            run.error,
            step=node if isinstance(node, str) else None,
            attempt=cast(int, an_object(attempts[-1], "a step's attempt")["attempt"]) if attempts else None,
        )
    if run.status == "stuck":
        suggestion = "Retry this stuck run from its last recorded step."
    elif err.retryable:
        suggestion = "Retry the run; the step that failed runs again."
    else:
        suggestion = "Fix the failing step's input or resource, then start a test run."
    return {
        "kind": err.kind,
        "code": err.code,
        "message": err.message,
        "userMessage": err.user_message,
        # A Stuck run is left for Retry whatever its code.
        "retryable": err.retryable or run.status == "stuck",
        "retryAfterSeconds": err.retry_after_seconds,
        "nodeId": err.step.id if err.step else None,
        "nodeName": err.step.name if err.step else None,
        "attempt": err.attempt,
        "of": err.of,
        "traceId": err.trace_id,
        "suggestion": suggestion,
        "details": err.details,
    }


async def ended_view(rt: Runtime, r: StoredRun) -> RunView:
    """run_view with how the run ended as a sentence (run_story.outcome_texts), for a route that returns one run."""
    return {**run_view(r), "outcomeText": (await run_story.outcome_texts(rt, [r.model_dump()])).get(r.id)}


def run_view(r: StoredRun) -> RunView:
    waiting = r.waiting
    return {
        "id": r.id,
        "workflowId": r.workflow_id,
        "version": r.version,
        "digest": r.digest,
        "mode": r.mode,
        "status": r.status,
        "outcome": r.outcome,
        "outcomeText": run_story.words(r.outcome) if r.outcome else None,
        "error": r.error,
        "input": r.input,
        "output": r.output,
        "waiting": RunWaitingView(node=waiting["node"], iteration=waiting["iteration"], payload=waiting["payload"])
        if waiting
        else None,
        "createdBy": r.created_by,
        "createdAt": r.created_at,
        "updatedAt": r.updated_at,
        "finishedAt": r.finished_at,
    }


async def startable(
    rt: Runtime, me: Principal, workflow_id: str, version: int | None, mode: Literal["live", "test"]
) -> StoredDefinition:
    """The definition row a run of `mode` starts on, once the caller may start it: any version for a test run (a
    builder's step), the live one for a live run (a builder, an admin or an API key of the team). Every way to start a
    run asks here, so they refuse the same callers."""
    pinned = require_key_reaches(me, "workflow", workflow_id)
    if pinned is not None and version not in (None, pinned):
        raise Forbidden(f"This API key starts version {pinned} of {workflow_id} only.", code="key_target")
    version = version if pinned is None else pinned
    stored = await definitions(rt).row(workflow_id, version, team=current_team())
    if stored is None:
        what = f"version {version} of " if version is not None else ""
        raise NotFound(f"{what}workflow definition {workflow_id}")
    if mode == "test":
        # A test run tries any version, a draft included, which is a builder's step: a builder or admin of the team
        # that owns the workflow, or of the acting team for one no team owns, which every team runs. An API key never
        # starts one (require_builder refuses a caller with no role).
        require_builder(
            me,
            area="workflows",
            team_id=stored.team_id or me.team_id,
            action="start a test run of",
            what=f"workflow {workflow_id}",
        )
    if mode == "live":
        # A builder or admin, or an API key of the team.
        require_runs_start(me, team_id=stored.team_id, what=f"workflow {workflow_id}")
        stored = await live_version(definitions(rt), workflow_id, version, team=current_team())
    return stored


def started_view(run: StoredRun, created: bool) -> RunStartedView:
    return {
        "runId": run.id,
        "workflowId": run.workflow_id,
        "version": run.version,
        "digest": run.digest,
        "status": run.status,
        "created": created,
    }


class StartInput(In):
    workflow_id: str
    # As for POST /v1/runs: the live version when left out, or the latest in test mode.
    version: int | None = None
    mode: Literal["live", "test"] = "live"
    # The start form's values (StartFormView.schema): a test email's from, subject, body and attachments, or a
    # Request trigger's input.
    values: dict[str, Any] = Field(default_factory=dict[str, Any])


@runs_router.post("/start", response_model=Envelope[RunStarted], status_code=202)
async def start_by_hand(rt: Rt, me: Me, body: StartInput) -> JSONResponse:
    """Starts a run from the start form its trigger declares (`startForm` on the definition), through the same entry
    the trigger's real source uses: a test email goes through the mailbox listener's own start, so its run gets the
    input and steps a mailbox email gets; a form's values become the input. The run records the person and how they
    started it (`startedBy.via`). The same callers may start it as for POST /v1/runs; 422 `no_start_form` for a trigger
    only its source starts, `email_filtered` for a test email the trigger's filters would skip.
    No request transaction: a test email's attachments go to files-service between its reads and its writes."""
    stored = await startable(rt, me, body.workflow_id, body.version, body.mode)
    run = await run_starts.start(rt, me, stored, body.values, body.mode)
    return ok(started_view(run, True), status=202)


@run_start_router.post(
    "",
    response_model=Envelope[RunStarted],
    status_code=202,
    responses={200: {"model": Envelope[RunStarted], "description": "The run key had started a run already"}},
)
async def start_engine_run(rt: Rt, me: Starter, body: EngineRunInput) -> JSONResponse:
    """Writes the run and its start work row in one transaction and returns at once: a worker runs it. With no worker
    running the run stays queued. A live run is refused (409) unless it pins the live version: `not_live` before a
    version is approved or for another version, `workflow_paused` while the workflow is paused. An API key scoped to
    one workflow starts that one only, on the version it pins when it pins one.
    No request transaction: the run and its work row keep start_run's own transaction, which a worker claims from."""
    stored = await startable(rt, me, body.workflow_id, body.version, body.mode)
    run, created = await start_run(
        runs(rt),
        stored,
        team_id=me.team_id,
        mode=body.mode,
        input=body.input,
        run_key=body.run_key,
        created_by=started_by(me),
        started_by_approver=approves_own_writes(me),
        after_seconds=body.after_seconds,
    )
    return ok(started_view(run, created), status=202 if created else 200)


@runs_router.get("", response_model=Envelope[LabelledListResult[RunRow]])
async def list_engine_runs(
    *,
    rt: Rt,
    me: Reader,
    q: ListQuery,
    workflow_id: Annotated[list[str] | None, Query(alias="workflowId")] = None,
    status: Annotated[list[str] | None, Query()] = None,
) -> JSONResponse:
    """The selected team's runs on the shared list contract, newest first, then by id; `workflowId` and `status`
    repeat to keep several; `facets.status` and `facets.workflowId` count the runs per status
    and per workflow under the other filters, and `labels.workflowId` names each counted workflow, so the workflow
    filter is filled from this reply. A scoped API key lists its own workflow's runs only.
    One transaction for the runs, outcomes and actors read; people's names and the masking policy come from
    platform-service with none open."""
    # Both reach the store through `q.filters`; declared so the document and the SDKs name them.
    del status
    pinned = None
    if (scope := key_scope(me)) is not None:
        if scope[0] != "workflow" or any(w != scope[1] for w in workflow_id or []):
            nothing = paged(
                [], 0, q.page, q.page_size, facets={"status": {}, "workflowId": {}}, labels={"workflowId": {}}
            )
            return ok(nothing)
        # A predicate, not a filter: the workflow facet, which leaves its own filter out, counts this one only.
        pinned = scope[1]
    # One transaction for this service's own reads; people's names and the masking policy are asked after it closes.
    async with isolation.request_transaction():
        listed = await runs(rt).listed(q, workflow_id=pinned)
        rows = listed["data"]
        known = await actor_reads(rt, [started_by_of(r) for r in rows])
        ended = await run_story.outcome_texts(rt, rows)
    who = await named_actors(rt, known)
    views = [
        await for_people(rt, r, run_view(r))
        | {
            "outcomeText": ended.get(r.id),
            "canCancel": can_cancel(me, r),
            "canRetry": can_retry(me, r),
            "canRedrive": can_redrive(me, r),
            "workflowName": r.workflow_name or UNNAMED_WORKFLOW,
            "startedBy": who.get(started_by_of(raw)),
        }
        for r, raw in ((ListedRun.model_validate(raw), raw) for raw in rows)
    ]
    return ok({**listed, "data": views})


@runs_router.get("/{run_id}", response_model=Envelope[RunDetail])
async def get_engine_run(rt: Rt, me: Reader, run_id: str) -> JSONResponse:
    """The run with every step from the journal: per node its input, output, port, attempts and errors.
    No request transaction. One transaction reads the run (a run the caller may not see is not found before any other
    service is asked) and what it is told from; names, the masking policy and file names come from platform-service and
    files-service with none open; the reply is then built from those answers."""
    store = runs(rt)
    with names_asked_once():
        async with isolation.request_transaction():
            run = await visible_run(rt, run_id, me)
            # run_story and actors still read the run as its stored mapping.
            raw = run.model_dump()
            steps = steps_view(await store.step_rows(run_id))
            decided = decisions_in(run_id, steps)
            reads = await run_story.story_reads(rt, raw, steps)
            ends, versions = await run_story.outcome_reads(rt, [raw])
            children = await started_runs(store, steps)
            known = await actor_reads(rt, [*reads.raws(raw, steps), started_by_of(raw)])
        who = await named_actors(rt, known)
        masking = await ai_steps_gate.people_see_masked(rt, run.team_id or None)
        names = getattr(rt, "team_names", None)
        team = (await names.name(run.team_id) if names is not None else None) or run.team_id
        await run_story.ask_story(rt, raw, steps, reads)
        files = await named(rt, run.team_id, [{"id": f["id"], "name": f["name"]} for f in files_in(run.input)])
        told = await run_story.story_view(
            rt, raw, steps, reads, who=who, team_name=team, scope=key_scope(me), masking=False
        )
    body = {
        **run_view(run),
        "outcomeText": run_story.outcome_sentences([raw], ends, versions).get(run.id),
        "workflowName": told.pop("workflowName"),
        "failure": run_failure(run, steps),
        "steps": steps,
        "children": children,
        "files": files,
        "decisions": [{**d, "by": who.get(d["by"]) if d["by"] else None} for d in decided],
        "result": run_result(raw, steps, reads.stored, decided=decided, names=who),
        "canCancel": can_cancel(me, run),
        "canRetry": can_retry(me, run),
        "canRedrive": can_redrive(me, run),
        "startedBy": who.get(started_by_of(raw)),
        "story": told,
    }
    if not masking:
        return ok(body)
    # Masking is on. The story sits outside the keys for_people masks, so it is masked here; the addresses the
    # run's email came from and arrived at are where it came from, not a customer's data, and stay shown.
    shown = _values_masked(body)
    shown["story"] = run_story.masked_story(shown["story"])
    shown = run_story.keep_channel(shown, body, reads.addresses)
    # The lines are sentences, so the addresses are kept inside them rather than by value.
    shown["story"]["lines"] = run_story.masked_lines(told["lines"], reads.addresses)
    return ok(shown)


# Where a run read carries what its steps worked on: the run's and each step's and attempt's input and output, an
# error's text, the values a decision carried and what a waiting step shows (payload). Ids, names and statuses around
# them are left alone (a run id's digits would read as an account number).
_VALUE_KEYS = frozenset({"input", "output", "error", "values", "payload"})


async def for_people(rt: Runtime, run: StoredRun, body: Any) -> Any:
    """`body`, read from `run`, as people see it: masked when the run's team has aiStepsMaskPersonalData on, the
    default. Every route that returns a run's or a step's values to a person answers through here."""
    return _values_masked(body) if await ai_steps_gate.people_see_masked(rt, run.team_id or None) else body


def _values_masked(body: Any) -> Any:
    """The run as people read it with masking on: every value under _VALUE_KEYS, wherever it sits. The stored
    run keeps the real values the steps after them use."""
    if isinstance(body, dict):
        return {k: masked(v) if k in _VALUE_KEYS else _values_masked(v) for k, v in cast(Json, body).items()}
    if isinstance(body, list):
        return [_values_masked(v) for v in cast(JsonList, body)]
    return body


async def started_runs(store: RunStore, steps: list[Json]) -> list[StartedRun]:
    """The runs the steps started, from each step's `runs` output (Start workflow), with their status now."""
    started: list[tuple[str, int, str]] = []
    for s in steps:
        out = s.get("output")
        listed = cast(list[JsonValue], out.get("runs") or []) if isinstance(out, dict) else []
        for i, row in enumerate(listed):
            if isinstance(row, dict) and row.get("runId"):
                started.append((str(s["nodeId"]), int(cast(int, row.get("index", i))), str(row["runId"])))
    found = {r.id: r for r in await store.many([rid for _, _, rid in started])}
    return [
        {
            "nodeId": node,
            "index": index,
            "runId": rid,
            "status": found[rid].status,
            "outcome": found[rid].outcome,
        }
        for node, index, rid in started
        if rid in found
    ]


def run_result(
    run: Json,
    steps: list[Json],
    stored: StoredDefinition | None,
    *,
    decided: list[Decision] | None = None,
    names: NamedActors | None = None,
) -> RunResultView | None:
    """The run's result: the End node it finished on, from the pinned definition and the journal, with the outcome and
    output the worker recorded on the run. An output that is the last Human Task's decision reads as people read it:
    the decision in words and who decided by name, since masking is for customer data and a staff address would show
    as [email]. `stored` is the version the run pinned (definitions.get), read by the caller."""
    if run["status"] == "cancelled" or run["outcome"] is None:
        return None
    nodes = engine_lifecycle.nodes_of(json_object(stored.definition) if stored else None)
    ends = [s for s in steps if nodes.get(str(s["nodeId"]), {}).get("type") == "ops.flow.end" and s["status"] == "ok"]
    end = ends[-1]["nodeId"] if ends else None
    name = str(nodes[str(end)].get("name") or end) if end else None
    output = run["output"]
    last = decided[-1] if decided else None
    if isinstance(output, dict) and last is not None and output.get("decision") == last["action"]:
        shown: Json = {
            **output,
            "decision": run_story.decision_label(nodes.get(str(last["nodeId"])), last["action"]),
        }
        who = (names or {}).get(str(output.get("by") or ""))
        if who:
            shown["by"] = who["name"]
        output = shown
    return {"node": end, "name": name, "outcome": run["outcome"] or "done", "output": output}


@runs_router.post("/{run_id}/cancel", response_model=Envelope[RunRow])
async def cancel_engine_run(rt: Rt, me: Me, run_id: str) -> JSONResponse:
    """Cancels a run that has not ended: a queued run never starts, a waiting run's review leaves Reviews, a running
    pass finishes and journals the step under way and begins no other. Cancelling a cancelled run returns it; a run
    that succeeded or failed is refused (409).
    No request transaction: the masking policy (platform-service) is asked after the writes, with none open."""
    run = await visible_run(rt, run_id, me)
    require_runs_cancel(me, team_id=run.team_id, started_by=run.created_by, what=f"run {run_id}")
    if run.status == "cancelled":
        return ok(await for_people(rt, run, await ended_view(rt, run)))
    cancelled, changed = await runs(rt).cancel(run_id, reason="by_user")
    if not changed or cancelled is None:
        raise Conflict(f"Run {run_id} has already {run.status}.", code="run_finished")
    await runs(rt).settle_parents(run_id, cancelled.created_by)
    await EventLog(rt.db).append(
        thread_id=run_id, team_id=run.team_id, run_id=run_id, type_="cancelled", node=None, data={"by": me.email}
    )
    return ok(await for_people(rt, cancelled, await ended_view(rt, cancelled)))


@runs_router.post("/{run_id}/retry", response_model=Envelope[RunRow])
async def retry_engine_run(rt: Rt, me: Me, run_id: str) -> JSONResponse:
    """Queues a Stuck run again from its last recorded step: recorded steps are not run again and a write
    with a record at the gateway is never sent again. Who may cancel the run may retry it; a run that is not Stuck is
    refused (409 run_not_stuck).
    No request transaction: the masking policy (platform-service) is asked after the write, with none open."""
    run = await visible_run(rt, run_id, me)
    require_runs_cancel(me, team_id=run.team_id, started_by=run.created_by, what=f"run {run_id}")
    retried, changed = await runs(rt).retry(run_id)
    if not changed or retried is None:
        raise Conflict("This run is no longer stuck, so there is nothing to retry.", code="run_not_stuck")
    await EventLog(rt.db).append(
        thread_id=run_id, team_id=run.team_id, run_id=run_id, type_="retried", node=None, data={"by": me.email}
    )
    return ok(
        await for_people(rt, retried, run_view(retried) | {"canCancel": can_cancel(me, retried), "canRetry": False})
    )


@runs_router.post("/{run_id}/redrive", response_model=Envelope[RunRow])
async def redrive_engine_run(rt: Rt, me: Me, run_id: str) -> JSONResponse:
    """Queues a Failed or Stuck run again from its failed step, on the version the run pinned: steps it recorded are
    not run again. A failed write is sent again, on its earlier approval, only when its answer proves it did nothing
    (refused, never sent, or refused before acting); any other is reconciled by its key at the gateway first. Who may
    cancel the run may redrive it; a run neither Failed nor Stuck is refused (409 run_not_redrivable).
    No request transaction: the masking policy (platform-service) is asked after the write, with none open."""
    run = await visible_run(rt, run_id, me)
    require_runs_cancel(me, team_id=run.team_id, started_by=run.created_by, what=f"run {run_id}")
    redriven, changed = await runs(rt).redrive(run_id)
    if not changed or redriven is None:
        raise Conflict("Only a failed or stuck run can be redriven.", code="run_not_redrivable")
    await EventLog(rt.db).append(
        thread_id=run_id, team_id=run.team_id, run_id=run_id, type_="redriven", node=None, data={"by": me.email}
    )
    view = run_view(redriven) | {"canCancel": can_cancel(me, redriven), "canRetry": False, "canRedrive": False}
    return ok(await for_people(rt, redriven, view))


class RunsFilter(In):
    """Which runs a bulk action takes: each given field narrows it. `kind` and `code` are the run's recorded error
    (ops_contracts.errors); `createdFrom` and `createdTo` bound when the run started, ISO times, the end excluded."""

    workflow_id: str | None = None
    kind: str | None = None
    code: str | None = None
    created_from: str | None = None
    created_to: str | None = None


class BulkRunsRequest(In):
    action: Literal["redrive", "cancel"]
    filter: RunsFilter = Field(default_factory=RunsFilter)


class BulkRunsResult(Out):
    action: str
    # The runs the action changed, and those the filter matched that the caller may not act on or that moved first.
    changed: list[str]
    skipped: list[str]


@runs_router.post("/bulk", response_model=Envelope[BulkRunsResult])
async def bulk_engine_runs(rt: Rt, me: Me, body: BulkRunsRequest) -> JSONResponse:
    """Redrives every Failed or Stuck run, or cancels every unfinished one, of the acting team that the filter
    matches, oldest first and at most BULK_LIMIT in one call. Each run is checked as its single route checks it: one
    the caller may not cancel is skipped and listed, never acted on.
    No request transaction: each run is changed in its own, as the single routes change it."""
    f = body.filter
    statuses = REDRIVABLE if body.action == "redrive" else ("queued", "running", "waiting", "stuck")
    pinned = scope[1] if (scope := key_scope(me)) is not None and scope[0] == "workflow" else None
    if pinned is not None and f.workflow_id not in (None, pinned):
        return ok({"action": body.action, "changed": [], "skipped": []})
    store = runs(rt)
    matched = await store.matching(
        statuses,
        workflow_id=pinned or f.workflow_id,
        kind=f.kind,
        code=f.code,
        created_from=f.created_from,
        created_to=f.created_to,
    )
    changed: list[str] = []
    skipped: list[str] = []
    for run in matched:
        if not (can_redrive(me, run) if body.action == "redrive" else can_cancel(me, run)):
            skipped.append(run.id)
            continue
        if body.action == "redrive":
            _, moved = await store.redrive(run.id)
        else:
            cancelled, moved = await store.cancel(run.id, reason="by_user")
            if moved and cancelled is not None:
                await store.settle_parents(run.id, cancelled.created_by)
        if not moved:
            skipped.append(run.id)
            continue
        changed.append(run.id)
        kind = "redriven" if body.action == "redrive" else "cancelled"
        await EventLog(rt.db).append(
            thread_id=run.id, team_id=run.team_id, run_id=run.id, type_=kind, node=None, data={"by": me.email}
        )
    return ok({"action": body.action, "changed": changed, "skipped": skipped})


@runs_router.post(
    "/set-aside-emails/{event_id}/run",
    response_model=Envelope[RunStarted],
    status_code=202,
    responses={200: {"model": Envelope[RunStarted], "description": "The email's run had started already"}},
)
async def run_set_aside_email(rt: Rt, me: Me, event_id: str) -> JSONResponse:
    """Run again on an email the mailbox listener set aside: its run starts on the workflow's live version under
    the email's own run key, as the person, and the kept copy of the email is dropped. Who may start the workflow may
    run it; 404 when there is no such email in the team or it already ran, 503 when Files did not store an attachment
    (the email stays set aside).
    No request transaction: the email's attachments are stored in files-service between its reads and its write."""
    event = await TriggerEvents(rt.db).set_aside(event_id)
    if event is None:
        raise NotFound(f"Set-aside email {event_id}")
    await startable(rt, me, str(event["workflow_id"]), None, "live")
    files = cast(FilesClient | None, rt.start_files)
    if files is None:
        raise ServiceUnavailable("An email's attachments are stored in Files, and this service has no Files URL.")
    try:
        started = await run_again(rt.db, files, event_id, by=started_by(me))
    except FilesRefused as e:
        raise ServiceUnavailable(f"Files did not store an attachment, so the email stays set aside: {e.message}") from e
    if started.run is None:
        raise Conflict("The workflow has started as many runs today as its trigger allows.", code="daily_cap")
    return ok(started_view(started.run, started.created), status=202 if started.created else 200)


async def event_frames(
    rt: Runtime, run_id: str, after: int, *, follow: bool, mask: bool = False
) -> AsyncGenerator[dict[str, str]]:
    log, store, cursor = EventLog(rt.db), runs(rt), after
    while True:
        batch = await log.run_events(run_id, run_id, cursor)
        for e in batch:
            cursor = e.seq
            shown = {**e.wire(), "data": masked(e.data)} if mask else e.wire()
            yield {"id": str(e.seq), "event": e.type, "data": json.dumps(shown, ensure_ascii=False)}
        if not follow:
            return
        run = await store.row(run_id)
        if not batch and (run is None or run.status in (*TERMINAL, "waiting")):
            return
        await asyncio.sleep(POLL_SECONDS)


@runs_router.get("/{run_id}/events", response_model=None, responses=SSE_RESPONSE)
async def engine_run_events(
    rt: Rt, me: Reader, run_id: str, after: int = 0, follow: bool = True
) -> EventSourceResponse:
    """The run's events with `seq` above `after`; the SSE `id` is the seq to resume from. With `follow` it keeps
    polling until the run ends or waits for a person.
    No request transaction: the masking policy comes from platform-service, and each frame's read opens its own."""
    run = await visible_run(rt, run_id, me)
    mask = await ai_steps_gate.people_see_masked(rt, run.team_id or None)
    return EventSourceResponse(event_frames(rt, run_id, after, follow=follow, mask=mask), sep="\n", ping=15)
