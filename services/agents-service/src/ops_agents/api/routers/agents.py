"""/v1/agents: the console's agents contract (apps/console/src/lib/api/contract.ts, `agents`) over the registry.

Rows are the console's `Agent`; versions its `AgentVersion`; a publish request answers with its `Review`. Bulk routes
are not served.

A route that only reads and writes this service's database answers in one request transaction (`Tx`): the versions,
the recent runs and the delete. The others take none, so no connection is held while another party answers: an
agent's reply names its stale grants from tools-service's directory (list, create, read, change, restore, pause), the
read names its team from platform-service, the publish preview and publish read the team's publish policy there and
ask models-service for the aliases, and the test, eval and job routes run the model.
"""

from __future__ import annotations

from typing import Annotated, Literal, TypeAlias, cast

from fastapi import APIRouter, Body, Depends, Query
from fastapi.responses import JSONResponse, Response
from pydantic import Field

from ops_access import can, require_provisioner
from ops_agent_kernel.layout import required_tools
from ops_agent_kernel.prompt_writer import Brief, Patterns
from ops_agents.activities.agent_limits import AgentLimits, check_limits, limits_of
from ops_agents.activities.agent_limits import wire as wire_limits
from ops_agents.activities.tool_directory import ToolsUnavailable
from ops_agents.app import agent_brief
from ops_agents.app.evals import parse_cases, run_eval
from ops_agents.domain.evals import TRIGGER_MANUAL
from ops_identity.fastapi import Tx
from ops_service_kit import narrow
from ops_service_kit.errors import Conflict, NotFound, Unprocessable, ValidationFailed
from ops_service_kit.http import Envelope, In, Json, JsonList, ListResult, Out
from ops_service_kit.ids import new_id, now_iso
from ops_service_kit.listing import ListQuery
from ops_store import isolation

from ...store.agent_registry import AgentRow, digest_of, refuse_stale
from ...store.graphs import StoredThread
from ...store.template_copies import TemplateCopies
from .. import eval_gate
from ..account_names import require_team_accounts
from ..agent_registry import (
    GUARDRAILS,
    AgentSpec,
    AgentView,
    WorkflowUse,
    a_day_ago,
    agent_review_body,
    agent_view,
    go_live,
    refuse_new_turns,
    registry,
    require_newest_draft,
    review_view,
    take_down,
    tasks_24h,
    version_state,
)
from ..agent_test import one_test_turn
from ..auth import Principal, caller, caller_in, caller_of, principal, reader_of, require_builder
from ..child_runs import engine_workflows, refusal, team_workflows
from ..deps import Runtime, runtime
from ..envelope import ok
from ..eval_runs import judge_for, prices_of, run_saved, version_turn
from ..guardrails import resolve_pins
from ..model_aliases import chat_aliases
from ..publish_policy import Decision, decide, team_document
from ..review_sla import sla_hours
from ..rights import rights
from ..runs import graph_store
from ..schemas import (
    Agent,
    AgentEvalRun,
    AgentPublishCheck,
    AgentRun,
    AgentTestTurn,
    AgentVersion,
    EvalRunRecord,
    MemorySettings,
    PublishDecisionFields,
    PublishReview,
    WidgetSettings,
)
from ..skills import check_pins_hold
from ..skills import pin_problems as skill_pin_problems
from ..team_names import team_name
from ..timers import arm_job
from ..widgets import published as published_widget
from ..workflow_registry import registry as workflow_registry
from .tool_catalog import ToolRows, directory_tools, known_tools

# The provisioning service reaches list, read, create, change and delete with a team-scoped token; every other
# route takes a person or an API key (`Me`).
router = APIRouter(prefix="/v1/agents", dependencies=[Depends(caller_in("agents"))])
Rt: TypeAlias = Annotated[Runtime, Depends(runtime)]  # noqa: UP040 - FastAPI reads Annotated aliases
Me: TypeAlias = Annotated[Principal, Depends(principal)]  # noqa: UP040
Cl: TypeAlias = Annotated[Principal, Depends(caller)]  # noqa: UP040
Reader: TypeAlias = Annotated[Principal, Depends(reader_of("agents"))]  # noqa: UP040

Channel = Literal["voice", "chat", "email", "api"]


class Guardrails(In):
    redact_pii: bool = True
    # Empty (None) is no cap; a number caps each turn. No ceiling: a real agent may need many.
    max_tool_calls_per_turn: int | None = Field(default=None, ge=1)
    # Empty here means the platform default of 50 model calls, never unlimited.
    max_model_calls_per_turn: int | None = Field(default=None, ge=1)
    # Per conversation: empty means the platform default (200 model calls, 5.00 cost), never unlimited.
    max_model_calls_per_conversation: int | None = Field(default=None, ge=1)
    max_cost_per_conversation: float | None = Field(default=None, gt=0)
    when_unsure: Literal["handoff", "ask", "decline"] = "handoff"
    blocked_topics: list[str] = Field(default_factory=list[str])


class AgentInput(In):
    name: str = Field(min_length=1, max_length=200)
    role: str = Field(min_length=1, max_length=400)
    # A models-service alias; empty runs the agent on the runtime's alias.
    model: str = ""
    channels: list[Channel] = Field(default_factory=lambda: ["chat"])
    instructions: str | None = None
    # Set by the provisioning service only; a person sending either is refused.
    template_id: str | None = Field(default=None, min_length=1, max_length=120)
    protection: Literal["system", "managed"] | None = None


class GuardrailPinInput(In):
    guardrail_id: str
    # None or 0 on a new pin takes the published version.
    version: int | None = None
    # Off: saved on the version and never checked; callers cannot override it per chat or run.
    enabled: bool = True


class WidgetPinInput(In):
    widget_id: str
    version: int | None = None


class AgentPatch(In):
    # The copy the change was made on: the agent's `version` and `digest` as last read. A save from an older copy is
    # refused (409 `stale_base`), so it never writes over a grant or an edit saved in between.
    base_version: int
    base_digest: str
    name: str | None = Field(default=None, min_length=1, max_length=200)
    role: str | None = Field(default=None, min_length=1, max_length=400)
    model: str | None = None
    channels: list[Channel] | None = None
    instructions: str | None = None
    tool_ids: list[str] | None = None
    collections: list[str] | None = None
    # search_knowledge may search every knowledge base of the agent's team; off, only `collections` (decision D19).
    all_team_knowledge_bases: bool | None = None
    # Which skills a person may pick from the / menu in a chat with this agent: team (any published team skill whose
    # tools it holds), attached (its own skills only) or off. Saved with the version.
    skill_menu: Literal["team", "attached", "off"] | None = None
    # The team account each app's calls use, app id to account name, as the whole map; checked when the agent is
    # published (each must be a team account of the app), never when saved, so a draft may name one not made yet.
    accounts: (
        dict[Annotated[str, Field(min_length=1, max_length=120)], Annotated[str, Field(min_length=1, max_length=200)]]
        | None
    ) = Field(default=None, max_length=20)
    guardrails: Guardrails | None = None
    # Guardrails attached by version: [{guardrailId, version}]; each saved with its version's rule.
    guardrail_pins: list[GuardrailPinInput] | None = None
    # What callers may override. Saved with the version and published through its review.
    limits: AgentLimits | None = None
    # Widgets by template: [{widgetId, version?}], each snapshotted from the library; version None takes the
    # latest published. Saved with the version and published through its review.
    widget_pins: list[WidgetPinInput] | None = None
    widgets: WidgetSettings | None = None
    # On or off, and which kinds.
    memory: MemorySettings | None = None
    # The agent as a brief. A save that carries it writes `role` and `instructions` from it (promptMode brief unless
    # the save says full); one that carries neither leaves an agent saved before the brief exactly as it was.
    brief: Brief | None = None
    prompt_mode: Literal["brief", "full"] | None = None
    patterns: Patterns | None = None
    note: str | None = None
    # Set by the provisioning service only.
    template_id: str | None = Field(default=None, min_length=1, max_length=120)
    protection: Literal["system", "managed"] | None = None


class PublishRequestInput(In):
    version: int
    note: str = ""


class PausedInput(In):
    paused: bool


class TestInput(In):
    # No run-as: a test runs as the person testing (there is no Run as), so a field naming someone else
    # would be accepted and ignored.
    message: str = Field(min_length=1)


class EvalCheckInput(In):
    type: str
    tool: str | None = None
    text: str | None = None
    # What a `judge` check asks of the reply, in words; required for that type (422 rubric_required).
    rubric: str | None = None


class EvalCaseContextInput(In):
    collections: list[str] = Field(default_factory=list[str])


class EvalCaseInput(In):
    name: str
    input: str
    context: EvalCaseContextInput | None = None
    checks: list[EvalCheckInput] = Field(default_factory=list[EvalCheckInput])


class EvalRunInput(In):
    # Empty is 422 from the use case, not Pydantic 400.
    # Omitted: run the cases saved on the agent and keep the run. Given: score these and keep nothing.
    cases: list[EvalCaseInput] | None = None


class JobInput(In):
    message: str = "Review held wires."
    due_at: str | None = None
    key: str = "job"


class JobArmed(Out):
    """What arming a job answers: the thread, the key, and whichever of the timer or the started run applies."""

    thread_id: str
    key: str
    duplicate: bool | None = None
    timer_id: str | None = None
    armed: bool | None = None
    status: str | None = None
    run_id: str | None = None


async def _directory(rt: Runtime) -> ToolRows | None:
    """What tools-service offers now, asked with nothing open; None when it cannot answer."""
    try:
        return await directory_tools(rt)
    except ToolsUnavailable:
        return None


async def _offered(rt: Runtime, directory: ToolRows | None) -> set[str] | None:
    """The tool ids offered: the directory's rows and the tenant's published workflows and agents (local reads);
    None when `directory` is None (tools-service could not answer)."""
    if directory is None:
        return None
    return {t["id"] for t in await known_tools(rt, listed=directory)}


def _stale(tool_ids: list[str], offered: set[str] | None) -> list[str]:
    """Granted ids the directory no longer offers (unpublished, hidden, drifted or deleted). `workflow:` grants are
    judged by the workflow runner. Unknown when tools-service cannot answer: an agent page should not fail on it, so
    nothing is reported stale then."""
    if offered is None:
        return []
    return [t for t in tool_ids if not t.startswith(("workflow:", "agent:")) and t not in offered]


def _agent_nodes(definition: Json) -> list[Json]:
    """The agents a published v1 definition pins: each `agent_turn` node's snapshotted definition."""
    nodes = cast(list[Json], definition.get("nodes") or [])
    return [cast(Json, cast(Json, n["config"])["agent"]) for n in nodes if n.get("kind") == "agent_turn"]


async def used_in_all(rt: Runtime) -> dict[str, list[WorkflowUse]]:
    """By agent id, the workflows that run it: its own one-step workflow once published (`agent:<id>`, the one its
    deployments go through), v1 workflows whose published version pins it (at the version pinned then), drafts naming
    its slug, and v2 workflows whose latest version has an agent step on it, which runs the agent's published version.
    The agent page's Settings and Deployments tabs both read this list, so they agree on where the agent runs."""
    agents = await registry(rt).rows()
    by_slug = {r.slug: r for r in agents}
    published = {r.id: r.published_version for r in agents}
    out: dict[str, list[WorkflowUse]] = {}
    for r in agents:
        if r.published_version is not None:
            use: WorkflowUse = {
                "workflowId": f"agent:{r.id}",
                "workflowName": "Its own one-step workflow",
                "pinnedVersion": r.published_version,
                "status": "paused" if r.paused else "live",
                # Publishes with the agent, so it is never behind, never republished by hand, and deleting the agent
                # takes it too: callers leave it out of those (and workflowIds lists only other workflows).
                "own": True,
            }
            out.setdefault(r.id, []).append(use)

    def add(agent_id: str, workflow_id: str, name: str, version: int | None, status: str) -> None:
        if version is None or any(u["workflowId"] == workflow_id for u in out.get(agent_id, [])):
            return
        out.setdefault(agent_id, []).append(
            {"workflowId": workflow_id, "workflowName": name, "pinnedVersion": int(version), "status": status}
        )

    assert rt.graph_store is not None
    for w in await workflow_registry(rt).rows():
        if w.status == "deleted":
            continue
        status = "paused" if w.status == "paused" else "live" if w.published_version is not None else "draft"
        if w.published_version is not None:
            v = await rt.graph_store.version(w.id, w.published_version)
            for a in _agent_nodes(v.definition if v else {}):
                add(str(a["id"]), w.id, w.name, int(cast(int | str | float, a["version"])), status)
        graph = w.draft or {}
        for node in cast(list[Json], graph.get("nodes") or []):
            data = cast(Json, node.get("data") or {})
            if (slug := data.get("agentSlug")) and (row := by_slug.get(str(slug))):
                add(row.id, w.id, w.name, published.get(row.id), "draft" if status == "draft" else status)
    for d in await engine_workflows(rt):
        definition = cast(Json, d["definition"] or {})
        for node in cast(list[Json], definition.get("nodes") or []):
            params = cast(Json, node.get("parameters") or {})
            if node.get("type") == "ops.ai.agent" and (aid := str(params.get("agent") or "")):
                add(aid, d["workflow_id"], d["name"], published.get(aid), "live")
    return out


async def _view(rt: Runtime, agent_id: str, *, directory: ToolRows | Literal["ask"] | None = "ask") -> AgentView:
    """The agent's reply. A read that holds one transaction passes the `directory` it asked tools-service for first;
    otherwise it is asked here."""
    if directory == "ask":
        directory = await _directory(rt)
    reg = registry(rt)
    row = await reg.row(agent_id)
    spec = (await reg.version(agent_id, row.version)).spec
    tasks = (await tasks_24h(rt)).get(agent_id, 0)
    # The reply is built from the same keys a listed page row carries (`_decorated` reads both).
    listed = {**row.model_dump(), "spec": spec, "tasks_24h": tasks}
    view = _decorated(listed, await _offered(rt, directory), (await used_in_all(rt)).get(agent_id, []))
    # What a save names with `version` as the copy it was made on; computed as the registry compares it.
    view["digest"] = digest_of(spec)
    return view


def _decorated(row: Json, offered: set[str] | None, uses: list[WorkflowUse]) -> AgentView:
    """An agent's reply from its row joined to its newest version's `spec` and its `tasks_24h`."""
    view = agent_view(row, cast(Json, row["spec"]), int(cast(int | str | float, row["tasks_24h"])))
    view["staleToolIds"] = _stale(view["toolIds"], offered)
    view["usedIn"] = sorted(uses, key=lambda u: u["workflowName"])
    view["workflowIds"] = sorted({u["workflowId"] for u in uses if not u.get("own")})
    view["templateId"], view["protection"] = row.get("template_id"), row.get("protection")
    return view


async def _checked_tools(rt: Runtime, tool_ids: list[str], granted: list[str]) -> list[str]:
    """The grants to save: a newly added id the directory does not offer is refused; one already granted that is no
    longer offered (stale) is dropped, so a stale grant never blocks saving the rest."""
    known = {t["id"] for t in await known_tools(rt)}
    # A plugin turned on moments ago is not in the list kept for 30 s: ask tools-service once more before refusing.
    if any(t not in known and t not in granted and not t.startswith(("workflow:", "agent:")) for t in tool_ids):
        known = {t["id"] for t in await known_tools(rt, fresh=True)}
    # A workflow or agent grant already held is kept while its target is paused or unpublished (it is simply not
    # offered until it is live again); a new one must be a published workflow or agent the directory offers now.
    offered = [t for t in tool_ids if t in known or (t.startswith(("workflow:", "agent:")) and t in granted)]
    unknown = [t for t in tool_ids if t not in offered and t not in granted]
    for t in unknown:
        if t.startswith("workflow:") and (why := await refusal(rt, t.removeprefix("workflow:"))) is not None:
            raise ValidationFailed(f"{why.message} An agent cannot be granted it.", code=why.code)
        if t.startswith("agent:"):
            aid = t.removeprefix("agent:")
            try:
                row = await registry(rt).row(aid)
            except NotFound as exc:
                raise ValidationFailed(f"Unknown tools: {t}.", code="unknown_tool") from exc
            if row.published_version is None:
                raise ValidationFailed(
                    f"Agent {aid} is not published, so it cannot be granted.",
                    code="not_published",
                )
            offered.append(t)
    leftover = [t for t in unknown if t not in offered]
    if leftover:
        raise ValidationFailed(f"Unknown tools: {', '.join(leftover)}.", code="unknown_tool")
    return offered


async def require_known_alias(rt: Runtime, alias: str) -> None:
    """Refuses a publish whose agent names an alias models-service does not serve; an empty alias uses the runtime's."""
    if not alias:
        return
    assert rt.model_aliases is not None
    known = await chat_aliases(rt.model_aliases)
    if alias not in known:
        raise Unprocessable(
            f"Model alias {alias} is not one models-service serves. Aliases: {', '.join(sorted(known))}.",
            code="unknown_model_alias",
        )


@router.get("", response_model=Envelope[ListResult[Agent]])
async def list_agents(
    *,
    rt: Rt,
    _: Reader,
    q: ListQuery,
    availability: Annotated[list[str] | None, Query()] = None,
    team_id: Annotated[list[str] | None, Query(alias="teamId")] = None,
) -> JSONResponse:
    """One page of the team's agents on the shared list contract, by name: `search` matches the name, role and slug;
    `sortBy` is one of name, updatedAt, tasks24h, version, teamId and availability; the filters `availability`,
    `teamId` and `templateId` narrow the page, and the first two are counted in `facets`."""
    # Read from `q.filters`; declared so the document and the SDKs name them.
    del availability, team_id
    directory = await _directory(rt)
    async with isolation.request_transaction():
        listed = await registry(rt).page(q, since=a_day_ago())
        offered = await _offered(rt, directory) if listed["data"] else None
        used = await used_in_all(rt) if listed["data"] else {}
    views = [_decorated(r, offered, used.get(str(r["id"]), [])) for r in listed["data"]]
    return ok({**listed, "data": views})


async def changeable(rt: Runtime, me: Principal, agent_id: str, action: str) -> AgentRow:
    """The agent's row once the caller may change it (auth.require_builder: the roles grid, in the team that owns it or,
    for one no team owns, the team the request acts in)."""
    row = await registry(rt).row(agent_id)
    require_builder(
        me,
        area="agents",
        team_id=row.team_id,
        action=action,
        what=f"agent {row.slug}",
        protection=row.protection,
    )
    return row


@router.post("", response_model=Envelope[Agent], status_code=201)
async def create_agent(rt: Rt, me: Cl, body: AgentInput) -> JSONResponse:
    if not me.team_id:
        # A dev session naming no team acts across teams; an agent belongs to exactly one.
        raise ValidationFailed(
            "Choose a team with the X-Team-Id header; an agent belongs to one team.", code="team_required"
        )
    require_builder(me, area="agents", team_id=me.team_id, action="create", what="an agent")
    if body.template_id is not None or body.protection is not None:
        require_provisioner(caller_of(me), "agents")
    spec: Json = {
        "name": body.name,
        "role": body.role,
        "model": body.model,
        "channels": [*body.channels],
        "instructions": body.instructions or f"You are {body.name}. {body.role}",
        "toolIds": [],
        "collections": [],
        "suggestions": [],
        "guardrails": GUARDRAILS,
    }
    aid = await registry(rt).create(
        spec, by=me.email, team_id=me.team_id, template_id=body.template_id, protection=body.protection
    )
    return ok(await _view(rt, aid), status=201)


@router.get("/{agent_id}", response_model=Envelope[Agent])
async def get_agent(rt: Rt, me: Reader, agent_id: str) -> JSONResponse:
    directory = await _directory(rt)
    async with isolation.request_transaction():
        view = await _view(rt, agent_id, directory=directory)
        rights_of = await rights(lambda action: changeable(rt, me, agent_id, action))
    # platform-service names the team with nothing open.
    return ok({**view, **await team_name(rt, cast(str | None, view.get("teamId"))), **rights_of})


@router.patch("/{agent_id}", response_model=Envelope[Agent])
async def update_agent(rt: Rt, me: Cl, agent_id: str, body: AgentPatch) -> JSONResponse:
    """Saves the patched spec as the agent's draft; what is live does not change until it is published.

    409 `stale_base` when `baseVersion` and `baseDigest` are not the newest copy (its details name who saved it and
    when): read the agent again and repeat the change."""
    reg = registry(rt)
    row = await changeable(rt, me, agent_id, "edit")
    if body.template_id is not None or body.protection is not None:
        require_provisioner(caller_of(me), "agents")
    newest = await reg.version(agent_id, row.version)
    # The draft as the patch below edits it, key by key.
    spec: Json = dict(newest.spec)
    # The copy the patch is applied to. The save below names it, so a save landing while tools-service or kb-service
    # is asked is refused too.
    read = (row.version, digest_of(spec))
    refuse_stale((body.base_version, body.base_digest), *read, saved_by=newest.saved_by, saved_at=newest.saved_at)
    patch = body.model_dump(
        exclude_none=True,
        exclude={
            "base_version",
            "base_digest",
            "note",
            "guardrails",
            "guardrail_pins",
            "limits",
            "widget_pins",
            "widgets",
            "memory",
            "brief",
            "prompt_mode",
            "patterns",
            "template_id",
            "protection",
        },
        by_alias=True,
    )
    if body.tool_ids is not None:
        patch["toolIds"] = await _checked_tools(rt, body.tool_ids, list(cast(list[str], spec.get("toolIds") or [])))
    if body.collections is not None:
        await _check_knowledge(rt, body.collections, list(cast(list[str], spec.get("collections") or [])))
    spec.update(patch)
    if body.guardrails is not None:
        spec["guardrails"] = body.guardrails.model_dump(by_alias=True)
    if body.tool_ids is not None or body.collections is not None:
        check_pins_hold(cast(AgentSpec, spec))
    if body.guardrail_pins is not None:
        wanted = [p.model_dump(by_alias=True) for p in body.guardrail_pins]
        spec["guardrailPins"] = await resolve_pins(rt, wanted, list(cast(list[Json], spec.get("guardrailPins") or [])))
    if body.limits is not None:
        spec["limits"] = wire_limits(body.limits)
    if body.widget_pins is not None:
        spec["widgetPins"] = [*await _widget_pins(rt, body.widget_pins)]
    if body.widget_pins is not None or body.tool_ids is not None:
        _check_widget_tools(spec)
    if body.widgets is not None:
        spec["widgets"] = body.widgets.model_dump(by_alias=True)
    if body.memory is not None:
        spec["memory"] = body.memory.model_dump(by_alias=True)
    spec = agent_brief.patched(
        spec,
        brief=body.brief,
        mode=body.prompt_mode,
        patterns=body.patterns,
        writes_prompt=body.instructions is not None or body.role is not None,
    )
    # Saved limits must still agree with the version: a changed model or a dropped tool without new limits is refused,
    # naming the limit, rather than leaving callers a choice the agent no longer has.
    if "limits" in spec:
        check_limits(limits_of(spec), spec)
    await reg.save(agent_id, spec, by=me.email, note=body.note or "", base=read)
    await reg.set_template(agent_id, template_id=body.template_id, protection=body.protection)
    return ok(await _view(rt, agent_id))


async def _check_knowledge(rt: Runtime, wanted: list[str], held: list[str]) -> None:
    """Each knowledge value a save adds is a knowledge base id kb-service knows (422 naming the rest): the runtime
    reads these as ids, so a name saved here would leave the agent citing nothing. Values the version already holds
    are kept even when their base is gone, so an agent stays saveable and the page shows them to remove.
    While kb-service cannot answer, a save that adds knowledge is refused (503) rather than accepted unchecked."""
    added = [k for k in wanted if k not in held]
    if not added:
        return
    known = {k.id for k in await rt.kbs().bases()}
    unknown = [k for k in added if k not in known]
    if unknown:
        raise Unprocessable(
            f"{', '.join(unknown)} {'is not a knowledge base' if len(unknown) == 1 else 'are not knowledge bases'}; "
            "pick knowledge bases from the list.",
            code="unknown_knowledge_base",
            details={"knowledgeBases": unknown},
        )


def _check_widget_tools(spec: Json) -> None:
    """Every tool a pinned widget's buttons ask for is one the version grants (422 naming it), so a widget never offers
    an action the agent cannot take; the same holds when a tool is taken away from an agent that pins such a widget."""
    granted = set(cast(list[str], spec.get("toolIds") or []))
    for pin in cast(list[Json], spec.get("widgetPins") or []):
        missing = [t for t in required_tools(pin["tree"]) if t not in granted]
        if missing:
            raise Unprocessable(
                f"The {pin['name']} widget needs {', '.join(missing)}; grant {'it' if len(missing) == 1 else 'them'} "
                "first, or choose another widget.",
                code="widget_needs_tool",
                details={"widgetId": pin["widgetId"], "tools": missing},
            )


async def _widget_pins(rt: Runtime, wanted: list[WidgetPinInput]) -> list[Json]:
    """Each wanted template snapshotted from the registry or the seeded library, so the version keeps exactly the tree
    it was reviewed with. An unknown, unpublished or retired template or version is refused naming it (422)."""
    out: list[Json] = []
    for w in wanted:
        found = await published_widget(rt, w.widget_id, w.version)
        if found is None:
            at = f"{w.widget_id} v{w.version}" if w.version else w.widget_id
            raise Unprocessable(f"widgetPins: no published widget {at}.", code="unknown_widget")
        out.append(found.model_dump(by_alias=True, exclude={"sample"}))
    return out


async def agent_users(rt: Runtime, agent_id: str) -> list[dict[str, str]]:
    """The team's workflows that run the agent, each `{kind, id, name}` once: those `used_in_all` names (its own
    one-step workflow aside, which goes with it), and every v2 workflow whose newest version, draft or live, has an
    agent step on it, since a draft names an agent before either is published."""
    out: list[dict[str, str]] = []

    def add(workflow_id: str, name: str) -> None:
        if all(u["id"] != workflow_id for u in out):
            out.append({"kind": "workflow", "id": workflow_id, "name": name})

    for use in (await used_in_all(rt)).get(agent_id, []):
        if not use.get("own"):
            add(str(use["workflowId"]), str(use["workflowName"]))
    for d in await team_workflows(rt):
        if d.get("archived_at"):
            continue
        for node in cast(list[Json], dict(d.get("definition") or {}).get("nodes") or []):
            if (
                node.get("type") == "ops.ai.agent"
                and dict(cast(Json, node.get("parameters") or {})).get("agent") == agent_id
            ):
                add(str(d["workflow_id"]), str(d["name"]))
    return out


@router.delete("/{agent_id}", status_code=204, response_model=None)
async def delete_agent(rt: Rt, me: Cl, _: Tx, agent_id: str) -> Response:
    """Deletes the agent. 409 `in_use` while a workflow of the team runs it, naming each in `details.usedBy`, so the
    person changes or removes those first."""
    await changeable(rt, me, agent_id, "delete")
    if users := await agent_users(rt, agent_id):
        names = ", ".join(u["name"] for u in users)
        raise Conflict(
            f"{names} {'runs' if len(users) == 1 else 'run'} this agent. Change or remove "
            f"{'it' if len(users) == 1 else 'them'} first.",
            code="in_use",
            details={"usedBy": users},
        )
    await registry(rt).delete(agent_id)
    await TemplateCopies(rt.db).removed_record("agent", agent_id)
    # Out of the catalogue once both writes stand, so a failed delete leaves the agent serving as before.
    take_down(rt, agent_id)
    return Response(status_code=204)


@router.get("/{agent_id}/versions", response_model=Envelope[list[AgentVersion]])
async def list_versions(rt: Rt, _: Reader, __: Tx, agent_id: str) -> JSONResponse:
    reg = registry(rt)
    row = await reg.row(agent_id)
    requests = await reg.requests("agent", agent_id)
    pending = next((r for r in requests if r.status == "pending"), None)
    rejected = {int(r.version) for r in requests if r.status == "rejected"}
    asked = {int(r.version) for r in requests}
    out: list[Json] = []
    for v in await reg.versions(agent_id):
        n = int(v.version)
        # History is what was published or put to a reviewer, plus the one draft; saves the per-save model
        # left behind are not listed.
        if not (v.published_at or n == row.version or n in asked):
            continue
        out.append(
            {
                "version": n,
                "note": v.note,
                "changes": v.changes,
                "current": n == row.published_version,
                "state": version_state(row, n, pending, rejected),
                "savedAt": v.saved_at,
                "savedBy": v.saved_by,
                **({"publishedAt": v.published_at, "publishedBy": v.published_by} if v.published_at else {}),
                **({"reviewId": v.review_id} if v.review_id else {}),
            }
        )
    return ok(out)


def _meta(thread: StoredThread) -> Json:
    return thread.meta_object()


@router.get("/{agent_id}/runs", response_model=Envelope[list[AgentRun]])
async def recent_runs(
    rt: Rt, _: Reader, __: Tx, agent_id: str, limit: Annotated[int, Query(ge=1, le=50)] = 10
) -> JSONResponse:
    """The agent's newest threads in the selected team: chats with it and runs of its own `agent:<id>` graph."""
    await registry(rt).row(agent_id)
    assert rt.graph_store is not None
    own = await rt.graph_store.thread_rows(f"agent:{agent_id}")
    chats = [t for t in await rt.graph_store.thread_rows("agent_wrapper") if _meta(t).get("agentId") == agent_id]
    rows = sorted([*own, *chats], key=lambda t: t.created_at, reverse=True)[:limit]
    return ok(
        [
            {
                "threadId": t.id,
                "kind": "chat" if t.graph == "agent_wrapper" else "graph",
                "title": str(_meta(t).get("title") or ""),
                "status": t.status,
                **({"version": t.version} if t.version is not None else {}),
                "startedAt": t.created_at,
                "updatedAt": t.updated_at,
            }
            for t in rows
        ]
    )


@router.post("/{agent_id}/versions/{version}/restore", response_model=Envelope[Agent])
async def restore_version(rt: Rt, me: Me, agent_id: str, version: int) -> JSONResponse:
    """Copies a version into a new draft; nothing publishes."""
    reg = registry(rt)
    await changeable(rt, me, agent_id, "restore a version of")
    old = await reg.version(agent_id, version)
    await reg.save(agent_id, dict(old.spec), by=me.email, note=f"Restored from v{version}")
    return ok(await _view(rt, agent_id))


async def _publish_decision(
    rt: Runtime,
    agent_id: str,
    row: AgentRow,
    version: int,
    document: Json | Literal["read"] | None = "read",
) -> Decision:
    """What the team's publish policy says about publishing `version`; the preview and the publish both ask here, so
    the dialog never promises what the publish does not do."""
    reg = registry(rt)
    spec = (await reg.version(agent_id, version)).spec
    live = await reg.version(agent_id, int(row.published_version)) if row.published_version else None
    return await decide(
        rt, area="agents", team_id=row.team_id, old=live.spec if live else None, new=spec, document=document
    )


@router.get("/{agent_id}/publish-preview", response_model=Envelope[PublishDecisionFields])
async def publish_preview(rt: Rt, me: Me, agent_id: str, version: Annotated[int, Query()]) -> JSONResponse:
    """Whether publishing the newest draft would wait for review, and why; nothing is opened or changed."""
    # The team's publish policy is read from platform-service first, with nothing open.
    document = await team_document(rt)
    async with isolation.request_transaction():
        row = await changeable(rt, me, agent_id, "publish")
        require_newest_draft(row, version)
        decision = await _publish_decision(rt, agent_id, row, version, document)
    return ok(decision.record())


async def _publish_problems(rt: Runtime, row: AgentRow, version: int, spec: Json) -> list[Json]:
    """What stops a version's publish: what its brief names and the agent lacks, what in the skills it pins must not
    run as stored, and its evals (`eval_gate`). The check and the publish both read this list."""
    brief = cast(list[Json], agent_brief.publish_problems(spec))
    pins = cast(list[Json], await skill_pin_problems(rt, spec))
    return [*brief, *pins, *await eval_gate.problems(rt, row, version)]


@router.get("/{agent_id}/publish-check", response_model=Envelope[AgentPublishCheck])
async def publish_check(rt: Rt, me: Me, _: Tx, agent_id: str, version: Annotated[int, Query()]) -> JSONResponse:
    """What stops the newest draft from being published, each with the field it is in (`position`): a reference the
    brief names that the agent does not hold. Nothing is opened or changed; the publish refuses the same list
    (422 `cannot_publish`). 422 `not_newest_draft` for any other version."""
    row = await changeable(rt, me, agent_id, "publish")
    require_newest_draft(row, version)
    problems = await _publish_problems(rt, row, version, (await registry(rt).version(agent_id, version)).spec)
    return ok({"canRequest": not problems, "problems": problems})


@router.post("/{agent_id}/publish-requests", response_model=Envelope[PublishReview], status_code=201)
async def request_publish(rt: Rt, me: Me, agent_id: str, body: PublishRequestInput) -> JSONResponse:
    """Opens an `agent_publish` review for the newest draft, or publishes it at once when the team's publish policy
    needs no review (`publish_preview` says which beforehand): its definition goes live and its graph compiles."""
    reg = registry(rt)
    row = await changeable(rt, me, agent_id, "publish")
    require_newest_draft(row, body.version)
    v = await reg.version(agent_id, body.version)
    spec = v.spec
    if problems := await _publish_problems(rt, row, body.version, spec):
        raise Unprocessable(
            "This version cannot be published yet: " + " ".join(str(p["message"]) for p in problems),
            code="cannot_publish",
            details={"problems": cast(JsonList, problems)},
        )
    for alias in limits_of(spec).allowed_models:
        await require_known_alias(rt, alias)
    named = cast(dict[str, str], spec.get("accounts") or {})
    await require_team_accounts(rt, str(row.team_id or ""), [("The agent", a, n) for a, n in named.items()])
    decision = await _publish_decision(rt, agent_id, row, body.version)
    approved = not decision.review_required
    review_body = {
        **agent_review_body(agent_id, spec, row, v, note=body.note, by=me.email),
        **decision.record(),
    }
    # Asking for the newest draft replaces a request still waiting on an older version (a seed change, a colleague's),
    # so the version that goes live is the one holding the newest grants.
    req = await reg.open_request(
        "agent",
        agent_id,
        body.version,
        note=body.note,
        by=me.email,
        body=review_body,
        approved=approved,
        replaces_older=True,
    )
    if approved:
        await reg.publish(agent_id, body.version, by=req.decided_by, review_id=req.id)
        if not row.paused:
            go_live(rt, agent_id, body.version, spec)
    return ok(
        review_view(req, name=narrow.required(spec, "name", str), slug=row.slug, sla_hours=await sla_hours(rt)),
        status=201,
    )


@router.post("/{agent_id}/paused", response_model=Envelope[Agent])
async def set_paused(rt: Rt, me: Me, agent_id: str, body: PausedInput) -> JSONResponse:
    """Pausing stops new chats and new agent-graph threads; resuming serves the published version again. A builder or
    admin of the owning team pauses, as for a workflow (engine_lifecycle)."""
    reg = registry(rt)
    row = await changeable(rt, me, agent_id, "pause" if body.paused else "resume")
    published = row.published_version
    if body.paused and published is None:
        raise Conflict("This agent has never been published, so there is nothing to pause.", code="not_published")
    await reg.set_paused(agent_id, body.paused)
    if body.paused:
        take_down(rt, agent_id)
    elif published is not None:
        go_live(rt, agent_id, int(published), (await reg.version(agent_id, int(published))).spec)
    return ok(await _view(rt, agent_id))


@router.post("/{agent_id}/test", response_model=Envelope[AgentTestTurn])
async def test_agent(rt: Rt, me: Me, agent_id: str, body: TestInput) -> JSONResponse:
    """One kernel turn on the newest version, draft or not, with no thread kept: the single-turn harness API scripts
    and use cases drive. A write tool stops at its gate, so the reply says where production would pause instead of
    acting. The console tests on a real thread instead (POST /chat/threads with test: true); this
    route goes once the use cases that call it move there."""
    row = await changeable(rt, me, agent_id, "test")
    return ok(await one_test_turn(rt, agent_id, body.message, row=row))


@router.post("/{agent_id}/eval-runs", response_model=Envelope[EvalRunRecord | AgentEvalRun])
async def create_eval_run(
    rt: Rt, me: Me, agent_id: str, body: Annotated[EvalRunInput, Body(default_factory=EvalRunInput)]
) -> JSONResponse:
    """Scores cases on the newest version through the same one-turn test path. With no cases in the body it runs the
    agent's saved cases, also on the live version when that is another one, and keeps the run (`EvalRunRecord`), so
    repeating it makes a second run. With cases in the body it scores them and keeps nothing (`AgentEvalRun`). Empty
    cases and an unknown check type are 422."""
    row = await registry(rt).row(agent_id)
    can(caller_of(me), "evals", "run", team=row.team_id, what=f"agent {row.slug}")
    if body.cases is None:
        return ok(await run_saved(rt, me, row, trigger=TRIGGER_MANUAL))
    cases = parse_cases([item.model_dump(by_alias=True) for item in body.cases])
    turn = version_turn(rt, row, int(row.version))
    return ok(await run_eval(agent_id, cases, turn, judge=judge_for(rt), prices=prices_of(rt)))


@router.post("/{agent_id}/jobs", response_model=Envelope[JobArmed], response_model_exclude_none=True)
async def create_job(rt: Rt, me: Me, agent_id: str, body: JobInput) -> JSONResponse:
    """Arm one due tick on the existing timer clock. A repeated key is one run."""
    await changeable(rt, me, agent_id, "run")
    await refuse_new_turns(rt, agent_id)
    delay = 0.0
    if body.due_at:
        from datetime import UTC, datetime  # noqa: PLC0415

        try:
            due = datetime.fromisoformat(body.due_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValidationFailed(f"{body.due_at!r} is not a date.", code="not_a_date") from exc
        if due.tzinfo is None:
            due = due.replace(tzinfo=UTC)
        delay = (due - datetime.now(UTC)).total_seconds()
    store = graph_store(rt)
    thread_id = new_id("gth")
    row, created = await store.open_thread(
        thread_id,
        f"agent:{agent_id}",
        {
            "ownerEmail": me.email,
            "startedBy": me.email,
            "schedule": {"agentId": agent_id, "message": body.message, "key": body.key},
        },
        me.team_id,
        now_iso(),
        external_key=f"job:{agent_id}:{body.key}",
    )
    if not created:
        return ok({"threadId": row.id, "duplicate": True, "key": body.key})
    armed = await arm_job(rt, row.id, delay=delay, key=body.key)
    return ok({"threadId": row.id, "key": body.key, **armed}, status=201)
